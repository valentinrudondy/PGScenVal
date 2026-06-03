"""Shared wind-plot time convention: ALL wind OUTPUT is US/Eastern, never UTC.

The user has repeatedly required ET on every wind plot/axis/day-slice. Default
to ET on any new wind figure; a UTC label is a defect. Only internal
computation/storage stays UTC (HRRR is UTC-native) — the conversion happens
here, at the presentation layer. See memory: feedback_eastern_time_output.
"""
ET = "US/Eastern"
HOUR_ET = "hour (ET)"


def to_et(obj):
    """Convert a tz-aware (UTC) DatetimeIndex-bearing Series/DataFrame to US/Eastern.
    After this, day-slicing by 'YYYY-MM-DD' and .index.hour are in Eastern time."""
    out = obj.copy()
    out.index = out.index.tz_convert(ET)
    return out
