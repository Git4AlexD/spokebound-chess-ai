"""CMA-ES (Covariance Matrix Adaptation Evolution Strategy) — the
optimizer spokebound.ai.evolve/evolve_fleet use to search Weights/
FleetRules space, in place of a hand-rolled crossover/mutation genetic
tournament.

Why this over a genetic algorithm: Weights and FleetRules are each just
10 plain, continuous, real-valued fields — a low-dimensional continuous
optimization problem, not a large or discrete one. A genetic algorithm
mutates each field independently, so it can never learn that two fields
move *together* (e.g. "when piece_safety goes up, material should come
down to compensate"); it also needs a full round-robin every generation
to rank its population, which wastes most of its games comparing two
mediocre candidates against each other. CMA-ES is the standard,
well-established optimizer for exactly this shape of problem: it
maintains a search distribution (a mean and a full covariance matrix)
over the parameter space and *adapts the covariance* every generation,
so it learns which fields move together, and its recombination weights
mean every candidate's evaluation — even a middling one — contributes
information to the next generation's search direction, not just
win/loss bragging rights against its neighbours.

This is a from-scratch, dependency-free implementation (no numpy — this
project has no third-party dependencies anywhere else, and one gets
introduced here only if that's ever explicitly asked for) of the
standard (mu/mu_w, lambda)-CMA-ES algorithm, following Hansen's own
tutorial ("The CMA Evolution Strategy: A Tutorial"). Small vectors and
matrices (these problems are 10-dimensional) make plain Python lists of
floats entirely fast enough — the real cost by orders of magnitude is
the fitness evaluation (playing real games), never the linear algebra.

Usage is an ask/tell loop, the conventional shape for this algorithm
(matching how established CMA-ES libraries structure it) — CMAES itself
never plays a game or knows what a Weights is; a caller like
spokebound.ai.evolve supplies the actual fitness evaluation:

    es = CMAES(initial_vector, sigma0=0.5, population_size=8)
    while not es.done(max_generations):
        candidates = es.ask()               # list of vectors to evaluate
        fitnesses = [my_fitness(c) for c in candidates]  # higher = better
        es.tell(candidates, fitnesses)
    best = es.mean                          # the incumbent, at any point

See run_cma_es for a generation-loop driver that also handles
converting to/from a genome type (Weights/FleetRules) and reporting
progress, so callers don't each reimplement that plumbing.
"""

import json
import math
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from spokebound.ai.selfplay import format_duration

Vector = list[float]
Matrix = list[list[float]]


# --- plain linear algebra (10x10 vectors/matrices — no need for numpy) ------

def _zeros(n: int) -> Vector:
    return [0.0] * n


def _identity(n: int) -> Matrix:
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def _vec_add(a: Vector, b: Vector) -> Vector:
    return [x + y for x, y in zip(a, b)]


def _vec_sub(a: Vector, b: Vector) -> Vector:
    return [x - y for x, y in zip(a, b)]


def _vec_scale(a: Vector, s: float) -> Vector:
    return [x * s for x in a]


def _dot(a: Vector, b: Vector) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: Vector) -> float:
    return math.sqrt(_dot(a, a))


def _outer(a: Vector, b: Vector) -> Matrix:
    return [[x * y for y in b] for x in a]


def _mat_add(A: Matrix, B: Matrix) -> Matrix:
    return [[A[i][j] + B[i][j] for j in range(len(A))] for i in range(len(A))]


def _mat_scale(A: Matrix, s: float) -> Matrix:
    return [[x * s for x in row] for row in A]


def _mat_vec(A: Matrix, v: Vector) -> Vector:
    return [_dot(row, v) for row in A]


def jacobi_eigh(A: Matrix, sweeps: int = 100,
               tol: float = 1e-12) -> tuple[Vector, Matrix]:
    """Return ``(eigenvalues, eigenvectors)`` for symmetric ``A``, via
    the classic cyclic Jacobi rotation method — eigenvectors as the
    *columns* of the returned matrix (``eigenvectors[i][k]`` is the
    i-th component of the k-th eigenvector), matching how CMAES uses
    them below. Simple, numerically stable, and plenty fast for the
    10x10 (or smaller) matrices this module ever deals with — a
    handful of sweeps typically already converges a matrix this size to
    well past float precision's own limits.
    """
    n = len(A)
    a = [row[:] for row in A]
    v = _identity(n)
    for _ in range(sweeps):
        off_diagonal = sum(a[i][j] * a[i][j]
                          for i in range(n) for j in range(n) if i != j)
        if off_diagonal < tol:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                apq = a[p][q]
                if abs(apq) < 1e-15:
                    continue
                theta = (a[q][q] - a[p][p]) / (2 * apq)
                sign = 1.0 if theta >= 0 else -1.0
                t = sign / (abs(theta) + math.sqrt(theta * theta + 1))
                c = 1 / math.sqrt(t * t + 1)
                s = t * c
                app, aqq = a[p][p], a[q][q]
                a[p][p] = c * c * app - 2 * s * c * apq + s * s * aqq
                a[q][q] = s * s * app + 2 * s * c * apq + c * c * aqq
                a[p][q] = a[q][p] = 0.0
                for i in range(n):
                    if i != p and i != q:
                        aip, aiq = a[i][p], a[i][q]
                        a[i][p] = a[p][i] = c * aip - s * aiq
                        a[i][q] = a[q][i] = s * aip + c * aiq
                for i in range(n):
                    vip, viq = v[i][p], v[i][q]
                    v[i][p] = c * vip - s * viq
                    v[i][q] = s * vip + c * viq
    eigenvalues = [a[i][i] for i in range(n)]
    return eigenvalues, v


# --- CMA-ES itself ------------------------------------------------------------

@dataclass
class _Params:
    n: int
    population_size: int
    mu: int
    weights: Vector
    mu_eff: float
    c_sigma: float
    d_sigma: float
    c_c: float
    c_1: float
    c_mu: float
    chi_n: float


def _default_params(n: int, population_size: int | None = None) -> _Params:
    lam = population_size or (4 + int(3 * math.log(n)))
    mu = lam // 2
    raw_weights = [math.log((lam + 1) / 2) - math.log(i) for i in range(1, mu + 1)]
    total = sum(raw_weights)
    weights = [w / total for w in raw_weights]
    mu_eff = 1.0 / sum(w * w for w in weights)
    c_sigma = (mu_eff + 2) / (n + mu_eff + 5)
    d_sigma = 1 + 2 * max(0.0, math.sqrt((mu_eff - 1) / (n + 1)) - 1) + c_sigma
    c_c = (4 + mu_eff / n) / (n + 4 + 2 * mu_eff / n)
    c_1 = 2 / ((n + 1.3) ** 2 + mu_eff)
    c_mu = min(1 - c_1, 2 * (mu_eff - 2 + 1 / mu_eff) / ((n + 2) ** 2 + mu_eff))
    chi_n = math.sqrt(n) * (1 - 1 / (4 * n) + 1 / (21 * n * n))
    return _Params(n, lam, mu, weights, mu_eff, c_sigma, d_sigma, c_c, c_1,
                  c_mu, chi_n)


class CMAES:
    """(mu/mu_w, lambda)-CMA-ES over a real-valued vector of dimension
    ``len(mean0)``. See the module docstring for the ask/tell usage
    pattern and why this algorithm over a genetic one.
    """

    def __init__(self, mean0: Vector, sigma0: float,
                population_size: int | None = None,
                rng: random.Random | None = None) -> None:
        self.params = _default_params(len(mean0), population_size)
        self.mean = list(mean0)
        self.sigma = sigma0
        self.C = _identity(self.params.n)
        self.p_sigma = _zeros(self.params.n)
        self.p_c = _zeros(self.params.n)
        self.generation = 0
        self.rng = rng or random.Random()
        self._eigen_b = _identity(self.params.n)
        self._eigen_d = [1.0] * self.params.n

    def ask(self) -> list[Vector]:
        """Return ``population_size`` fresh candidate vectors, sampled
        from the current search distribution — the batch to evaluate
        and hand back to :meth:`tell`."""
        eigenvalues, b = jacobi_eigh(self.C)
        # Numerical noise can push a near-zero eigenvalue slightly
        # negative; clamp before sqrt rather than let a stray tiny
        # negative blow up into a complex/NaN step.
        d = [math.sqrt(max(value, 1e-20)) for value in eigenvalues]
        self._eigen_b, self._eigen_d = b, d
        candidates = []
        for _ in range(self.params.population_size):
            z = [self.rng.gauss(0.0, 1.0) for _ in range(self.params.n)]
            y = _mat_vec(b, [d[i] * z[i] for i in range(self.params.n)])
            candidates.append(_vec_add(self.mean, _vec_scale(y, self.sigma)))
        return candidates

    def tell(self, candidates: list[Vector], fitnesses: list[float]) -> None:
        """Update the search distribution from one generation's
        results. ``fitnesses`` is higher-is-better, matched by index to
        ``candidates`` (as returned by :meth:`ask`, in any order — this
        does its own ranking)."""
        p = self.params
        ranked = sorted(zip(fitnesses, candidates), key=lambda fc: -fc[0])
        selected = [genome for _, genome in ranked[:p.mu]]
        old_mean = self.mean
        y_selected = [_vec_scale(_vec_sub(x, old_mean), 1 / self.sigma)
                     for x in selected]
        y_w = _zeros(p.n)
        for w, y in zip(p.weights, y_selected):
            y_w = _vec_add(y_w, _vec_scale(y, w))
        self.mean = _vec_add(old_mean, _vec_scale(y_w, self.sigma))

        b, d = self._eigen_b, self._eigen_d
        # C^{-1/2} = B diag(1/D) B^T
        inv_sqrt_c_y = _mat_vec(b, [_dot([b[i][k] for i in range(p.n)], y_w) / d[k]
                                    for k in range(p.n)])
        self.p_sigma = _vec_add(
            _vec_scale(self.p_sigma, 1 - p.c_sigma),
            _vec_scale(inv_sqrt_c_y,
                      math.sqrt(p.c_sigma * (2 - p.c_sigma) * p.mu_eff)))
        p_sigma_norm = _norm(self.p_sigma)
        self.sigma *= math.exp((p.c_sigma / p.d_sigma) * (p_sigma_norm / p.chi_n - 1))

        self.generation += 1
        expected_norm = math.sqrt(1 - (1 - p.c_sigma) ** (2 * self.generation))
        h_sigma = 1.0 if (p_sigma_norm / expected_norm
                         < (1.4 + 2 / (p.n + 1)) * p.chi_n) else 0.0
        self.p_c = _vec_add(
            _vec_scale(self.p_c, 1 - p.c_c),
            _vec_scale(y_w, h_sigma * math.sqrt(p.c_c * (2 - p.c_c) * p.mu_eff)))

        rank_one = _outer(self.p_c, self.p_c)
        delta_h = (1 - h_sigma) * p.c_c * (2 - p.c_c)
        rank_mu = [[0.0] * p.n for _ in range(p.n)]
        for w, y in zip(p.weights, y_selected):
            rank_mu = _mat_add(rank_mu, _mat_scale(_outer(y, y), w))
        self.C = _mat_add(
            _mat_add(_mat_scale(self.C, 1 - p.c_1 - p.c_mu),
                    _mat_scale(_mat_add(rank_one, _mat_scale(self.C, delta_h)),
                              p.c_1)),
            _mat_scale(rank_mu, p.c_mu))
        # Keep C symmetric — accumulated float error can drift it
        # slightly asymmetric over many generations, and jacobi_eigh
        # assumes a genuinely symmetric matrix.
        self.C = [[(self.C[i][j] + self.C[j][i]) / 2 for j in range(p.n)]
                 for i in range(p.n)]


# --- crash resumability: save/restore the whole search distribution --------

def save_state(path: Path, es: CMAES, field_names: tuple[str, ...],
               label: str, seed: int | None) -> None:
    """Persist everything needed to reconstruct ``es`` exactly (mean,
    sigma, covariance, both evolution paths, generation number, and the
    population size its own params were derived from) — called after
    every generation's tell() in run_cma_es, so a crash or interruption
    loses at most the generation in progress, never the whole run.

    Written to a temporary file first, then atomically replaced onto
    ``path`` (os.replace is atomic on both Windows and POSIX) — a crash
    during the save itself still leaves the previous generation's valid
    state in place rather than a half-written, unloadable file, right
    when a crash makes that most likely to matter.
    """
    state = {
        "label": label, "field_names": list(field_names), "seed": seed,
        "population_size": es.params.population_size,
        "generation": es.generation, "sigma": es.sigma, "mean": es.mean,
        "C": es.C, "p_sigma": es.p_sigma, "p_c": es.p_c,
    }
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp_path, path)


def load_state(path: Path) -> dict:
    """Read back a state dict written by :func:`save_state`."""
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _restore(state: dict, rng: random.Random) -> CMAES:
    """Reconstruct the exact CMAES a saved state describes — params are
    re-derived fresh from field count and the saved population_size
    (a pure function of those two, see _default_params), not saved
    directly, so this stays correct even if _default_params' own
    formulas ever change between the run that saved this state and the
    one resuming it."""
    es = CMAES(state["mean"], state["sigma"], state["population_size"], rng=rng)
    es.C = state["C"]
    es.p_sigma = state["p_sigma"]
    es.p_c = state["p_c"]
    es.generation = state["generation"]
    return es


# --- generic driver: genome <-> vector, generation loop, reporting ----------

def _to_vector(genome, field_names: tuple[str, ...]) -> Vector:
    return [getattr(genome, field) for field in field_names]


def _from_vector(cls: type, field_names: tuple[str, ...], vector: Vector):
    return cls(**dict(zip(field_names, vector)))


def run_cma_es(
       *, label: str, seed_genome, sigma0: float,
       evaluate_population: Callable[[list, object], list[float]],
       generations: int, population_size: int | None = None,
       results_path=None, log_path=None, state_path: Path | None = None,
       resume: bool = True, seed: int | None = None):
    """Run CMA-ES for ``generations`` generations, starting the search
    distribution at ``seed_genome`` (any Weights/FleetRules-shaped
    frozen dataclass, converted to/from a plain vector via its own
    ``field_names()``), and return the final incumbent (the search
    distribution's own mean — CMA-ES's own best current estimate,
    stronger than trusting any single generation's best individual,
    which can be a lucky outlier).

    ``evaluate_population(genomes, incumbent)`` is called once per
    generation with this generation's ``population_size`` candidates
    (already converted back to real genome objects) and the search
    distribution's own current mean, *before* this generation's update
    — also converted to a real genome, so a caller can use it as a
    moving-target opponent alongside whatever fixed opposition it
    already plays (see spokebound.ai.evolve, which plays every
    candidate against both its fixed benchmark bots and this incumbent,
    so the bar keeps rising as the population improves instead of
    plateauing once the fixed opposition stops being a real test). Must
    return each candidate's fitness, same order, higher-is-better.
    Prints progress every generation (current sigma — the search
    distribution's own shrinking "how sure am I" — plus a running ETA)
    and appends to ``results_path``/``log_path`` if given.

    ``state_path``, if given, is where this run's whole search
    distribution is saved after every generation (see save_state) — so
    a crash or interruption loses at most the generation in progress,
    not the whole run. With ``resume=True`` (the default) and a valid
    state file already there whose ``field_names`` match this genome
    type, the run picks up from the saved generation instead of
    starting over; a mismatched state file raises rather than silently
    using it wrong. Pass ``resume=False`` (spokebound.ai.evolve exposes
    this as a --fresh command-line flag) to ignore any saved state and
    start over regardless of what's there.
    """
    cls = type(seed_genome)
    field_names = seed_genome.field_names()

    resumed_from = None
    if resume and state_path is not None and state_path.exists():
        state = load_state(state_path)
        if state["field_names"] != list(field_names):
            raise ValueError(
                f"Saved state at {state_path} was written for fields "
                f"{state['field_names']}, not {list(field_names)} — looks "
                f"like it belongs to a different run. Delete it or pass "
                f"resume=False to start fresh instead.")
        es = _restore(state, random.Random(seed))
        resumed_from = state["generation"]
    else:
        es = CMAES(_to_vector(seed_genome, field_names), sigma0, population_size,
                  rng=random.Random(seed))

    if resumed_from:
        header = (f"\nResuming CMA-ES — {label} from generation "
                 f"{resumed_from} (of {generations} total)\n")
    else:
        header = (
            f"{'#' * 60}\n"
            f"  CMA-ES — {label}\n"
            f"  {es.params.population_size} candidates/generation, "
            f"{generations} generations, sigma0={sigma0}\n"
            f"{'#' * 60}\n")
    print(header, flush=True)
    if results_path is not None:
        mode = "a" if resumed_from else "w"
        with results_path.open(mode, encoding="utf-8") as f:
            f.write(header)

    run_started = time.monotonic()
    generation_seconds: list[float] = []
    start_generation = (resumed_from + 1) if resumed_from else 1
    for generation in range(start_generation, generations + 1):
        started = time.monotonic()
        vectors = es.ask()
        genomes = [_from_vector(cls, field_names, v) for v in vectors]
        incumbent = _from_vector(cls, field_names, es.mean)
        fitnesses = evaluate_population(genomes, incumbent)
        es.tell(vectors, fitnesses)
        if state_path is not None:
            save_state(state_path, es, field_names, label, seed)
        elapsed = time.monotonic() - started
        generation_seconds.append(elapsed)

        best_index = max(range(len(fitnesses)), key=fitnesses.__getitem__)
        avg_generation = sum(generation_seconds) / len(generation_seconds)
        remaining = generations - generation
        eta_text = (f" — ~{format_duration(avg_generation * remaining)} left"
                   if remaining else " — done")
        line = (f"Generation {generation}/{generations}: "
               f"best this gen scored {fitnesses[best_index]:.2f}, "
               f"sigma={es.sigma:.4f} "
               f"({format_duration(elapsed)}{eta_text})")
        print(line, flush=True)
        if results_path is not None:
            with results_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        if log_path is not None:
            record = {
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "generation": generation, "sigma": es.sigma,
                "mean": dict(zip(field_names, es.mean)),
                "fitnesses": fitnesses,
                "candidates": [dict(zip(field_names, v)) for v in vectors],
            }
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

    total = f"\nCMA-ES finished in {format_duration(time.monotonic() - run_started)}."
    print(total, flush=True)
    if results_path is not None:
        with results_path.open("a", encoding="utf-8") as f:
            f.write(total + "\n")
    return _from_vector(cls, field_names, es.mean)
