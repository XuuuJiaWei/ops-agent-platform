"""Custom AIOpsLab problem definitions used by the OpsPilot bridge.

These problems keep AIOpsLab's official lifecycle (app deploy, workload,
session, evaluator) but replace the flagd feature-flag faults with real
Chaos Mesh faults (pod failure / network loss) targeted at the
OpenTelemetry demo (Astronomy Shop) workload.
"""
