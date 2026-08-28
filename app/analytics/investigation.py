"""Root cause investigation and anomaly detection engine."""

from collections import defaultdict
from decimal import Decimal
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from app.analytics.queries import (
    fetch_overall_metrics,
    fetch_gateway_performance,
    fetch_hourly_segment_metrics,
)
from app.analytics.metrics import (
    calculate_success_rate,
    calculate_revenue_at_risk,
    calculate_composite_score,
)

# Configurable minimum sample size to avoid small-sample false positives
MIN_SAMPLE_SIZE = 50


def run_investigation(db: Session) -> Dict[str, Any]:
    """Run full deterministic root-cause analysis over the dataset.

    Scans the transaction logs, groups them by segments, and dynamically
    discovers anomalous time windows and candidate incidents using a composite
    ranking algorithm. Exposes complete structured metrics and evidence.
    """
    overall = fetch_overall_metrics(db)
    if overall["total_count"] == 0:
        return {
            "overall_metrics": overall,
            "gateway_metrics": [],
            "top_candidates": [],
            "time_analysis": {
                "hourly": [],
                "daily": [],
            },
            "revenue_at_risk_summary": {
                "estimated_revenue_at_risk": 0.0,
            },
            "investigation_status": "no_data",
        }

    gateway_perf = fetch_gateway_performance(db)
    hourly_metrics = fetch_hourly_segment_metrics(db)

    # Extract all unique dates in the dataset
    unique_dates = sorted(list(set(row["date"] for row in hourly_metrics)))

    # Group hourly metrics by segment (gateway, payment_method, bank)
    segments = defaultdict(list)
    for row in hourly_metrics:
        key = (row["gateway_code"], row["payment_method_code"], row["bank_code"])
        segments[key].append(row)

    # Define standard candidate hour windows to evaluate (to find anomalous blocks)
    hour_windows = [
        list(range(24)),  # Full Day
        [18, 19, 20, 21],  # Evening Peak
        [18, 19, 20, 21, 22, 23],
        [12, 13, 14, 15, 16, 17],  # Afternoon
        [6, 7, 8, 9, 10, 11],  # Morning
        [0, 1, 2, 3, 4, 5],  # Late Night
        [16, 17, 18, 19, 20, 21, 22, 23],  # Evening/Night
        [17, 18, 19, 20, 21, 22],
    ]

    # Generate candidate date ranges of length 1 to 3 consecutive days
    date_ranges = []
    for i in range(len(unique_dates)):
        for length in range(1, 4):
            if i + length <= len(unique_dates):
                date_ranges.append(unique_dates[i : i + length])

    candidates = []

    # Analyze each segment across all candidate windows
    for (gateway, pm_code, bank_code), cells in segments.items():
        total_attempts = sum(c["total_count"] for c in cells)
        # Skip small overall segments
        if total_attempts < MIN_SAMPLE_SIZE:
            continue

        # Map date/hour cells for constant-time lookups
        cell_map = {(c["date"], c["hour"]): c for c in cells}

        for d_range in date_ranges:
            for h_window in hour_windows:
                in_attempts = 0
                in_successes = 0
                in_attempted_val = Decimal("0.00")
                in_successful_val = Decimal("0.00")

                out_attempts = 0
                out_successes = 0
                out_attempted_val = Decimal("0.00")
                out_successful_val = Decimal("0.00")

                # Accumulate segment stats inside vs. outside this candidate window
                for cell in cells:
                    is_in_window = cell["date"] in d_range and cell["hour"] in h_window
                    if is_in_window:
                        in_attempts += cell["total_count"]
                        in_successes += cell["success_count"]
                        in_attempted_val += cell["attempted_value"]
                        in_successful_val += cell["successful_value"]
                    else:
                        out_attempts += cell["total_count"]
                        out_successes += cell["success_count"]
                        out_attempted_val += cell["attempted_value"]
                        out_successful_val += cell["successful_value"]

                # Candidate window must have at least MIN_SAMPLE_SIZE attempts both inside and outside
                if in_attempts < MIN_SAMPLE_SIZE or out_attempts < MIN_SAMPLE_SIZE:
                    continue

                affected_rate = calculate_success_rate(in_successes, in_attempts)
                baseline_rate = calculate_success_rate(out_successes, out_attempts)
                rate_drop = baseline_rate - affected_rate

                # Drop must be meaningful (> 5 percentage points)
                if rate_drop <= 5.0:
                    continue

                # Consistency = fraction of active hourly cells in the window showing a drop of >= 5% below baseline_rate
                total_cells_in_window = 0
                anomalous_cells_in_window = 0
                for d in d_range:
                    for h in h_window:
                        cell = cell_map.get((d, h))
                        if cell:
                            total_cells_in_window += 1
                            cell_rate = calculate_success_rate(
                                cell["success_count"], cell["total_count"]
                            )
                            if (baseline_rate - cell_rate) >= 5.0:
                                anomalous_cells_in_window += 1

                consistency = (
                    anomalous_cells_in_window / total_cells_in_window
                    if total_cells_in_window > 0
                    else 0.0
                )

                # Skip candidates that are inconsistent or lack persistence
                if consistency < 0.5:
                    continue

                # Calculate revenue at risk
                rev_at_risk_dict = calculate_revenue_at_risk(
                    in_attempted_val, in_successful_val, baseline_rate
                )
                est_loss = float(rev_at_risk_dict["estimated_revenue_at_risk"])

                # Calculate composite score (incorporates log-scale rev-at-risk, sample size, and consistency)
                score = calculate_composite_score(in_attempts, rate_drop, consistency, est_loss)

                candidates.append(
                    {
                        "gateway_code": gateway,
                        "payment_method_code": pm_code,
                        "bank_code": bank_code,
                        "suspected_dates": d_range,
                        "suspected_hours": h_window,
                        "baseline_success_rate": baseline_rate,
                        "affected_success_rate": affected_rate,
                        "rate_drop": round(rate_drop, 2),
                        "sample_size": in_attempts,
                        "attempted_value": float(in_attempted_val),
                        "successful_value": float(in_successful_val),
                        "revenue_at_risk": round(est_loss, 2),
                        "consistency": round(consistency, 2),
                        "ranking_score": score,
                    }
                )

    # Sort candidates by composite ranking score descending
    candidates.sort(key=lambda x: x["ranking_score"], reverse=True)

    # 3. Compile Time Analysis (Daily and Hourly performance)
    hourly_perf_map = defaultdict(lambda: {"attempts": 0, "successes": 0})
    daily_perf_map = defaultdict(lambda: {"attempts": 0, "successes": 0})

    for row in hourly_metrics:
        h = row["hour"]
        d = row["date"]
        hourly_perf_map[h]["attempts"] += row["total_count"]
        hourly_perf_map[h]["successes"] += row["success_count"]
        daily_perf_map[d]["attempts"] += row["total_count"]
        daily_perf_map[d]["successes"] += row["success_count"]

    hourly_analysis = []
    for h in sorted(hourly_perf_map.keys()):
        attempts = hourly_perf_map[h]["attempts"]
        successes = hourly_perf_map[h]["successes"]
        rate = calculate_success_rate(successes, attempts)
        hourly_analysis.append(
            {
                "hour": h,
                "total_count": attempts,
                "success_rate": rate,
            }
        )

    daily_analysis = []
    for d in sorted(daily_perf_map.keys()):
        attempts = daily_perf_map[d]["attempts"]
        successes = daily_perf_map[d]["successes"]
        rate = calculate_success_rate(successes, attempts)
        daily_analysis.append(
            {
                "date": d,
                "total_count": attempts,
                "success_rate": rate,
            }
        )

    # Sum up total revenue at risk from top candidates
    total_rev_at_risk = sum(c["revenue_at_risk"] for c in candidates[:3])

    return {
        "overall_metrics": {
            "total_count": overall["total_count"],
            "success_count": overall["success_count"],
            "failed_count": overall["failed_count"],
            "success_rate": overall["success_rate"],
            "attempted_value": float(overall["attempted_value"]),
            "successful_value": float(overall["successful_value"]),
            "failed_value": float(overall["failed_value"]),
        },
        "gateway_metrics": gateway_perf,
        "top_candidates": candidates,
        "time_analysis": {
            "hourly": hourly_analysis,
            "daily": daily_analysis,
        },
        "revenue_at_risk_summary": {
            "estimated_revenue_at_risk": round(total_rev_at_risk, 2),
        },
        "investigation_status": "complete" if candidates else "healthy",
    }
