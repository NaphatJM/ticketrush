from opentelemetry.sdk.metrics.export import MetricReader


def metric_value(reader: MetricReader, name: str, **attributes) -> float:
    """Sum of the cumulative points of `name` whose attributes include `attributes`; histograms count observations."""
    data = reader.get_metrics_data()
    total = 0
    for resource_metrics in data.resource_metrics if data else ():
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name != name:
                    continue
                for point in metric.data.data_points:
                    if attributes.items() <= dict(point.attributes).items():
                        total += point.count if hasattr(point, 'count') else point.value
    return total
