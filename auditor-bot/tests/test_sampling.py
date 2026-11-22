import pytest

from fiscal.sampling import required_sample_size, stratified_sample, wilson_interval, z_score


def test_z_score_95():
    assert z_score(0.95) == pytest.approx(1.95996, abs=1e-4)


def test_wilson_known_value():
    # valor de referência: 8 sucessos em 10, IC 95% de Wilson ≈ (0.490, 0.943)
    lo, hi = wilson_interval(8, 10)
    assert lo == pytest.approx(0.490, abs=0.002)
    assert hi == pytest.approx(0.943, abs=0.002)


def test_wilson_zero_failures_has_positive_upper_bound():
    lo, hi = wilson_interval(0, 50)
    assert lo == 0.0
    assert 0.05 < hi < 0.10  # Wald daria exatamente 0; Wilson não


def test_wilson_bounds_and_shrinks_with_n():
    lo1, hi1 = wilson_interval(10, 100)
    lo2, hi2 = wilson_interval(100, 1000)
    assert 0 <= lo1 < 0.1 < hi1 <= 1
    assert (hi2 - lo2) < (hi1 - lo1)


def test_wilson_edge_cases():
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson_interval(5, 3)


def test_required_sample_size_classic_values():
    assert required_sample_size(0.05, 0.95) == 385
    assert required_sample_size(0.03, 0.95) == 1068


def test_required_sample_size_finite_population_correction():
    n = required_sample_size(0.05, 0.95, population=500)
    assert 200 < n < 385
    assert required_sample_size(0.05, 0.95, population=100) <= 100


def test_stratified_sample_proportional_and_reproducible():
    items = [("a", i) for i in range(80)] + [("b", i) for i in range(20)]
    s1 = stratified_sample(items, 20, key=lambda x: x[0], seed=1)
    s2 = stratified_sample(items, 20, key=lambda x: x[0], seed=1)
    assert s1 == s2
    assert len(s1) == 20
    assert sum(1 for x in s1 if x[0] == "a") == 16
    assert len(set(s1)) == len(s1)  # sem repetição


def test_stratified_sample_keeps_every_stratum():
    items = [("a", i) for i in range(98)] + [("b", 0), ("c", 0)]
    sample = stratified_sample(items, 10, key=lambda x: x[0])
    assert {k for k, _ in sample} == {"a", "b", "c"}
    assert len(sample) == 10


def test_sample_larger_than_population_returns_all():
    assert len(stratified_sample([1, 2, 3], 10, key=str)) == 3
