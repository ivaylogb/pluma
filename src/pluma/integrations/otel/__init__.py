"""Pluma OpenTelemetry integration.

Converters from OTel span exports (OTLP/JSON, Jaeger, bare span
array) to integration-watcher's trace JSONL input.
"""

from .otel_to_traces import TraceRecord, otel_to_traces

__all__ = ["TraceRecord", "otel_to_traces"]
