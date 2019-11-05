"""
Waveframe specific utilities.
"""
import obspy
import pandas as pd
from typing import Union

import numpy as np
from obsplus.constants import TIME_COLUMNS
from obsplus.constants import (
    WaveformClient,
    bulk_waveform_arg_type,
    NSLC,
    BULK_WAVEFORM_COLUMNS,
    wave_type,
)
from obsplus.utils.time import to_datetime64, to_utc
from obsplus.utils.pd import apply_funcs_to_columns, order_columns
from obsplus.utils.waveforms import get_waveform_client, stream_bulk_split
from obsplus.exceptions import DataFrameContentError


class DfPartDescriptor:
    """
    A simple descriptor granting access to various parts of a dataframe.
    """

    def __init__(self, df_name):
        self._df_name = df_name

    def __set_name__(self, owner, name):
        self._name = name

    def __get__(self, instance, owner):
        return getattr(instance, self._df_name)[self._name]


def _time_to_utc(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert time columns in a pandas dataframe to UTCDateTime objects.
    """
    df = df.copy()
    col_funcs = {name: to_utc for name in TIME_COLUMNS}
    return apply_funcs_to_columns(df, col_funcs)


def _time_cols_to_datetime64(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert time columns in a dataframe to numpy datetimes.
    """
    col_funcs = {name: to_datetime64 for name in TIME_COLUMNS}
    return apply_funcs_to_columns(df, col_funcs)


def _get_waveforms_bulk(
    waveform_client: WaveformClient, bulk: bulk_waveform_arg_type
) -> obspy.Stream:
    """
    Get bulk waveforms from waveform client.

    Either 1) call waveform_client's get_waveforms_bulk method (if it exists)
    or 2) iterate the bulk_arg and call get_waveforms for each.

    Parameters
    ----------
    waveform_client
        Any object with a ``get_waveforms`` method.
    bulk
        A list of tuples containing:
            (network, station, location, channel, starttime, endtime)
    """
    if hasattr(waveform_client, "get_waveforms_bulk"):
        return waveform_client.get_waveforms_bulk(bulk)
    # iterate each bulk, collect streams and return
    out = obspy.Stream()
    for bulk_arg in bulk:
        out += waveform_client.get_waveforms(*bulk_arg)
    return out


def _get_bulk_args(stats_df):
    """
    Get bulk args for waveform request.

    Raise ValueError if any invalid data found.
    """
    df = _time_to_utc(stats_df[list(BULK_WAVEFORM_COLUMNS)])
    # next convert to list of tuples and return.
    return df.to_records(index=False).tolist()


def _get_stats_dataframe(df):
    """

    Parameters
    ----------
    df

    Returns
    -------

    """

    def rename_startdate_enddate(df):
        """ rename startdate, enddate to starttime endtime """
        col_set = set(df.columns)
        if "startdate" in col_set and "starttime" not in col_set:
            df = df.rename(columns={"startdate": "starttime"})
        if "enddate" in col_set and "endtime" not in col_set:
            df = df.rename(columns={"enddate": "endtime"})
        return df

    def _check_nslc_codes(df):
        """ Ensure there are no wildcards in NSLC columns. """
        for code in NSLC:
            has_qmark = df[code].str.contains("?", regex=False).any()
            has_star = df[code].str.contains("*", regex=False).any()
            if has_qmark or has_star:
                msg = f"columns {NSLC} cannot contain * or ?, column {code} does"
                raise DataFrameContentError(msg)
        return df

    def _check_starttime_endtime(df):
        """ Ensure all starttimes are less than endtimes. """
        # starttimes must be <= endtime
        invalid_time_range = df["starttime"] >= df["endtime"]
        if invalid_time_range.any():
            msg = f"all values in starttime must be <= endtime"
            raise DataFrameContentError(msg)
        return df

    def _check_missing_data(df):
        """ There should be no missing data in the required columns."""
        if df[list(BULK_WAVEFORM_COLUMNS)].isnull().any().any():
            msg = f"Missing values in columns {BULK_WAVEFORM_COLUMNS} found. "
            raise DataFrameContentError(msg)
        return df

    # Order the columns and ensure datetime64 dtypes are in dataframe
    df = (
        rename_startdate_enddate(df)
        .pipe(_time_cols_to_datetime64)
        .pipe(order_columns, required_columns=BULK_WAVEFORM_COLUMNS)
        .pipe(_check_nslc_codes)
        .pipe(_check_missing_data)
        .pipe(_check_starttime_endtime)
    )
    return df


def _get_timeseries_df_from_client(
    waveforms: Union[wave_type, pd.DataFrame], bulk
) -> pd.DataFrame:
    """ Given a waveform client return a dataframe containing time series. """
    # If a dataframe was already passed simply return it.
    if isinstance(waveforms, pd.DataFrame):
        return waveforms
    client = get_waveform_client(waveforms)
    # Get a stream of waveforms.
    if not isinstance(waveforms, obspy.Stream):
        waveforms = _get_waveforms_bulk(client, bulk)
    # There isn't guaranteed to be a trace for each bulk arg, so use
    # stream_bulk_split to make it so.
    st_list = stream_bulk_split(waveforms, bulk, fill_value=np.NaN)
    # make sure the data are merged together with a sensible fill value
    arrays = []
    for st in st_list:
        assert len(st) in {0, 1}, "st should either be empty or len 1"
        if not len(st):  # empty data still needs an entry
            arrays.append(np.array(np.NaN))
            continue
        arrays.append(st[0].data)

    return pd.DataFrame(arrays)
