#!/usr/bin/env python3
"""
Automated E2E Test Suite Runner for Alpaca AI Trading Agents Hackathon.
Executes all 4 tiers of the opaque-box verification suite and outputs structured reporting.
Exits with return code 0 on pass, or 1 on failure.
"""

from __future__ import annotations

import sys
import time
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import test modules
from tests.e2e.test_tier1_features import TestTier1FeatureCoverage
from tests.e2e.test_tier2_boundaries import TestTier2BoundaryCases
from tests.e2e.test_tier3_combinations import TestTier3CrossFeatureCombinations
from tests.e2e.test_tier4_scenarios import TestTier4RealWorldScenarios


@dataclass
class TierResult:
    name: str
    tier_number: int
    total_tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_seconds: float
    is_success: bool


class StructuredE2ERunner:
    """Executes all 4 test tiers and generates an auditable, structured summary."""

    TIERS = [
        (1, "Tier 1: Feature Coverage (F1.1 - F3.2)", TestTier1FeatureCoverage),
        (2, "Tier 2: Boundary & Corner Cases", TestTier2BoundaryCases),
        (3, "Tier 3: Cross-Feature Combinations", TestTier3CrossFeatureCombinations),
        (4, "Tier 4: Real-World Workload Scenarios", TestTier4RealWorldScenarios),
    ]

    def __init__(self, verbosity: int = 1):
        self.verbosity = verbosity

    def run_tier(self, tier_num: int, tier_name: str, test_case_cls) -> TierResult:
        """Executes a single tier and records structured metrics."""
        suite = unittest.TestLoader().loadTestsFromTestCase(test_case_cls)
        start_time = time.perf_counter()

        # Run with buffered output
        runner = unittest.TextTestRunner(
            verbosity=self.verbosity,
            buffer=True,
        )
        result = runner.run(suite)
        elapsed = time.perf_counter() - start_time

        total = result.testsRun
        failed = len(result.failures)
        errors = len(result.errors)
        skipped = len(result.skipped)
        passed = total - (failed + errors + skipped)
        is_success = result.wasSuccessful()

        return TierResult(
            name=tier_name,
            tier_number=tier_num,
            total_tests=total,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            duration_seconds=elapsed,
            is_success=is_success,
        )

    def run_all(self) -> tuple[bool, list[TierResult]]:
        """Executes all tiers and prints a structured summary table."""
        print("=" * 80)
        print("ALPACA AI TRADING AGENTS HACKATHON — E2E TEST SUITE RUNNER")
        print(f"Timestamp (UTC): {datetime.now(timezone.utc).isoformat()}")
        print(f"Working Directory: {PROJECT_ROOT}")
        print("Methodology: 4-Tier Opaque-Box Requirement Verification")
        print("=" * 80)
        print()

        tier_results: list[TierResult] = []
        overall_success = True

        for tier_num, tier_name, test_cls in self.TIERS:
            print(f"[*] Running Tier {tier_num}: {tier_name} ...", end=" ", flush=True)
            res = self.run_tier(tier_num, tier_name, test_cls)
            tier_results.append(res)
            if res.is_success:
                print(f"PASSED ({res.passed}/{res.total_tests} in {res.duration_seconds:.3f}s)")
            else:
                print(f"FAILED ({res.failed} failures, {res.errors} errors in {res.duration_seconds:.3f}s)")
                overall_success = False

        print()
        print("=" * 80)
        print("E2E EXECUTION SUMMARY REPORT")
        print("=" * 80)
        print(f"{'Tier':<8} {'Name':<42} {'Total':<7} {'Pass':<6} {'Fail':<6} {'Skip':<6} {'Time':<8}")
        print("-" * 80)

        total_tests = 0
        total_pass = 0
        total_fail = 0
        total_errors = 0
        total_skip = 0
        total_time = 0.0

        for r in tier_results:
            total_tests += r.total_tests
            total_pass += r.passed
            total_fail += r.failed
            total_errors += r.errors
            total_skip += r.skipped
            total_time += r.duration_seconds

            tier_label = f"Tier {r.tier_number}"
            time_str = f"{r.duration_seconds:.2f}s"
            print(f"{tier_label:<8} {r.name[:40]:<42} {r.total_tests:<7} {r.passed:<6} {r.failed + r.errors:<6} {r.skipped:<6} {time_str:<8}")

        print("-" * 80)
        print(f"{'TOTAL':<8} {'All 4 Tiers Combined':<42} {total_tests:<7} {total_pass:<6} {total_fail + total_errors:<6} {total_skip:<6} {total_time:.2f}s")
        print("=" * 80)

        if overall_success:
            print(">>> OVERALL VERDICT: ALL E2E TIERS PASSED (100% SUCCESS) <<<")
            print(">>> EXIT CODE: 0 <<<")
        else:
            print(">>> OVERALL VERDICT: ONE OR MORE E2E TIERS FAILED <<<")
            print(">>> EXIT CODE: 1 <<<")
        print("=" * 80)

        return overall_success, tier_results


def main() -> int:
    runner = StructuredE2ERunner(verbosity=1)
    success, _ = runner.run_all()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
