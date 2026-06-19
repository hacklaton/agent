from .operators import (
    RunClustering,
    GetDashboardCorrelation,
    FlagBorderlineCases,
    PublishRiskAlert,
)

def register(plugin):
    plugin.register(RunClustering)
    plugin.register(GetDashboardCorrelation)
    plugin.register(FlagBorderlineCases)
    plugin.register(PublishRiskAlert)
