""" tests for various utility functions """
import itertools
import textwrap
from pathlib import Path
from typing import Sequence

import numpy as np
import obspy
import obspy.core.event as ev
import pandas as pd
import pytest
from obspy import UTCDateTime
from obspy.core.event import Catalog, Event, Origin

import obsplus
import obsplus.utils.misc
from obsplus.constants import NSLC, NULL_SEED_CODES, DISTANCE_COLUMNS
from obsplus.utils.docs import compose_docstring
from obsplus.utils.misc import yield_obj_parent_attr, get_distance_df
from obsplus.utils.pd import filter_index, filter_df
from obsplus.utils.time import to_utc, get_reference_time, to_datetime64, to_timestamp


def append_func_name(list_obj):
    """ decorator to append a function name to list_obj """

    def wrap(func):
        list_obj.append(func.__name__)
        return func

    return wrap


# ------------------------- module level fixtures


class TestGetReferenceTime:
    """ tests for getting reference times from various objects """

    time = obspy.UTCDateTime("2009-04-01")
    fixtures = []

    # fixtures
    @pytest.fixture(scope="class")
    @append_func_name(fixtures)
    def utc_object(self):
        return obspy.UTCDateTime(self.time)

    @pytest.fixture(scope="class")
    @append_func_name(fixtures)
    def timestamp(self):
        return self.time.timestamp

    @pytest.fixture(scope="class")
    @append_func_name(fixtures)
    def event(self):
        origin = Origin(time=self.time, latitude=47, longitude=-111.7)
        return Event(origins=[origin])

    @pytest.fixture(scope="class")
    @append_func_name(fixtures)
    def catalog(self, event):
        return Catalog(events=[event])

    @pytest.fixture(scope="class")
    def picks(self):
        t1, t2 = UTCDateTime("2016-01-01"), UTCDateTime("2015-01-01")
        picks = [ev.Pick(time=t1), ev.Pick(time=t2), ev.Pick()]
        return picks

    @pytest.fixture(scope="class")
    def event_only_picks(self, picks):
        return ev.Event(picks=picks)

    @pytest.fixture(scope="class", params=fixtures)
    def time_outputs(self, request):
        """ meta fixtures to gather up all the input types"""
        fixture_value = request.getfixturevalue(request.param)
        return get_reference_time(fixture_value)

    # tests
    def test_is_utc_date(self, time_outputs):
        """ ensure the output is a UTCDateTime """
        assert isinstance(time_outputs, obspy.UTCDateTime)

    def test_time_equals(self, time_outputs):
        """ ensure the outputs are equal to time on self """
        assert time_outputs == self.time

    def test_empty_event_raises(self):
        """ ensure an empty event will raise """
        event = ev.Event()
        with pytest.raises(ValueError):
            get_reference_time(event)

    def test_event_with_picks(self, event_only_picks):
        """ test that an event with picks, no origin, uses smallest pick """
        t_expected = UTCDateTime("2015-01-01")
        t_out = get_reference_time(event_only_picks)
        assert t_expected == t_out

    def test_stream(self):
        """ Ensure the start of the stream is returned. """
        st = obspy.read()
        out = get_reference_time(st)
        assert out == min([tr.stats.starttime for tr in st])


class TestIterate:
    def test_none(self):
        """ None should return an empty tuple """
        assert obsplus.utils.misc.iterate(None) == tuple()

    def test_object(self):
        """ A single object should be returned in a tuple """
        assert obsplus.utils.misc.iterate(1) == (1,)

    def test_str(self):
        """ A single string object should be returned as a tuple """
        assert obsplus.utils.misc.iterate("hey") == ("hey",)


class TestDocsting:
    """ tests for obsplus' simple docstring substitution function. """

    def test_docstring(self):
        """ Ensure docstrings can be composed with the docstring decorator. """
        params = textwrap.dedent(
            """
        Parameters
        ----------
        a: int
            a
        b int
            b
        """
        )

        @compose_docstring(params=params)
        def testfun1():
            """
            {params}
            """

        assert "Parameters" in testfun1.__doc__
        line = [x for x in testfun1.__doc__.split("\n") if "Parameters" in x][0]
        base_spaces = line.split("Parameters")[0]
        assert len(base_spaces) == 12


class TestReplaceNullSeedCodes:
    """ tests for replacing nulish NSLC codes for various objects. """

    @pytest.fixture
    def null_stream(self,):
        """ return a stream with various nullish nslc codes. """
        st = obspy.read()
        st[0].stats.location = ""
        st[1].stats.channel = "None"
        st[2].stats.network = "null"
        st[0].stats.station = "--"
        return st

    @pytest.fixture
    def null_catalog(self):
        """ create a catalog object, hide some nullish station codes in
        picks and such """

        def make_wid(net="UU", sta="TMU", loc="01", chan="HHZ"):
            kwargs = dict(
                network_code=net, station_code=sta, location_code=loc, channel_code=chan
            )
            wid = ev.WaveformStreamID(**kwargs)
            return wid

        cat = obspy.read_events()
        ev1 = cat[0]
        # make a pick
        picks = []
        for val in NULL_SEED_CODES:
            wid = make_wid(loc=val)
            picks.append(ev.Pick(waveform_id=wid, time=obspy.UTCDateTime()))
        ev1.picks.extend(picks)
        return cat

    @pytest.fixture
    def null_inventory(self):
        """ Create an inventory with various levels of nullish chars. """
        inv = obspy.read_inventory()
        # change the location codes, all other codes are required
        inv[0][0][1].location_code = "--"
        inv[0][0][2].location_code = "None"
        inv[0][1][1].location_code = "nan"
        return inv

    def test_stream(self, null_stream):
        """ ensure all the nullish chars are replaced """
        st = obsplus.utils.misc.replace_null_nlsc_codes(null_stream.copy())
        for tr1, tr2 in zip(null_stream, st):
            for code in NSLC:
                code1 = getattr(tr1.stats, code)
                code2 = getattr(tr2.stats, code)
                if code1 in NULL_SEED_CODES:
                    assert code2 == ""
                else:
                    assert code1 == code2

    def test_catalog(self, null_catalog):
        """ ensure all nullish catalog chars are replaced """
        cat = obsplus.utils.misc.replace_null_nlsc_codes(null_catalog.copy())
        for pick, _, _ in yield_obj_parent_attr(cat, cls=ev.Pick):
            wid = pick.waveform_id
            assert wid.location_code == ""

    def test_inventory(self, null_inventory):
        def _valid_code(code):
            """ return True if the code is valid. """
            return code not in NULL_SEED_CODES

        inv = obsplus.utils.misc.replace_null_nlsc_codes(null_inventory)

        for net in inv:
            assert _valid_code(net.code)
            for sta in net:
                assert _valid_code(sta.code)
                for chan in sta:
                    assert _valid_code(chan.code)
                    assert _valid_code(chan.location_code)


class TestFilterDf:
    @pytest.fixture
    def example_df(self):
        """ create a simple df for testing. Example from Chris Albon. """
        raw_data = {
            "first_name": ["Jason", "Molly", "Tina", "Jake", "Amy"],
            "last_name": ["Miller", "Jacobson", "Ali", "Milner", "Cooze"],
            "age": [42, 52, 36, 24, 73],
            "preTestScore": [4, 24, 31, 2, 3],
            "postTestScore": [25, 94, 57, 62, 70],
        }
        return pd.DataFrame(raw_data, columns=list(raw_data))

    def test_filter_index(self, crandall_dataset):
        """ Tests for filtering index with filter index function. """
        # this is mainly here to test the time filtering, because the bank
        # operations pass this off to the HDF5 kernel.
        index = crandall_dataset.waveform_client.read_index(network="UU")
        mean_ns = index.starttime.astype(int).mean()
        t1 = to_datetime64(obspy.UTCDateTime(ns=int(mean_ns)))
        t2 = index.endtime.max()
        kwargs = dict(network="UU", station="*", location="*", channel="*")
        bool_ind = filter_index(index, starttime=t1, endtime=t2, **kwargs)
        assert (~np.logical_not(bool_ind)).any()

    def test_string_basic(self, example_df):
        """ test that specifying a string with no matching works. """
        out = filter_df(example_df, first_name="Jason")
        assert out[0]
        assert not out[1:].any()

    def test_string_matching(self, example_df):
        """ unix style matching should also work. """
        # test *
        out = filter_df(example_df, first_name="J*")
        assert {"Jason", "Jake"} == set(example_df[out].first_name)
        # test ???
        out = filter_df(example_df, first_name="J???")
        assert {"Jake"} == set(example_df[out].first_name)

    def test_str_sequence(self, example_df):
        """ Test str sequences find values in sequence. """
        out = filter_df(example_df, last_name={"Miller", "Jacobson"})
        assert out[:2].all()
        assert not out[2:].any()

    def test_non_str_single_arg(self, example_df):
        """ test that filter index can be used on Non-nslc columns. """
        # test non strings
        out = filter_df(example_df, age=42)
        assert out[0]
        assert not out[1:].any()

    def test_non_str_sequence(self, example_df):
        """ ensure sequences still work for isin style comparisons. """
        out = filter_df(example_df, age={42, 52})
        assert out[:2].all()
        assert not out[2:].any()

    def test_bad_parameter_raises(self, example_df):
        """ ensure passing a parameter that doesn't have a column raises. """
        with pytest.raises(ValueError):
            filter_df(example_df, bad_column=2)


class TestMisc:
    """ misc tests for small utilities """

    @pytest.fixture
    def apply_test_dir(self, tmpdir):
        """ create a test directory for applying functions to files. """
        path = Path(tmpdir)
        with (path / "first_file.txt").open("w") as fi:
            fi.write("hey")
        with (path / "second_file.txt").open("w") as fi:
            fi.write("ho")
        return path

    def test_no_std_out(self, capsys):
        """ ensure print doesn't propagate to std out when suppressed. """
        with obsplus.utils.misc.no_std_out():
            print("whisper")
        # nothing should have made it to stdout to get captured. The
        # output shape seems to be dependent on pytest version (or something).
        capout = capsys.readouterr()
        if isinstance(capout, tuple):
            assert [not x for x in capout]
        else:
            assert not capout.out

    def test_to_timestamp(self):
        """ ensure things are properly converted to timestamps. """
        ts1 = to_timestamp(10, None)
        ts2 = obspy.UTCDateTime(10).timestamp
        assert ts1 == ts2
        on_none = to_timestamp(None, 10)
        assert on_none == ts1 == ts2

    def test_graceful_progress_fail(self, monkeypatch):
        """ Ensure a progress bar that cant update returns None """
        from progressbar import ProgressBar

        def raise_exception():
            raise Exception

        monkeypatch.setattr(ProgressBar, "start", raise_exception)
        assert obsplus.utils.misc.get_progressbar(100) is None

    def test_apply_or_skip(self, apply_test_dir):
        """ test applying a function to all files or skipping """
        processed_files = []

        def func(path):
            processed_files.append(path)
            if "second" in path.name:
                raise Exception("I dont want seconds")
            return path

        out = list(obsplus.utils.misc.apply_to_files_or_skip(func, apply_test_dir))
        assert len(processed_files) == 2
        assert len(out) == 1


class TestToNumpyDateTime:
    """ Tests for converting UTC-able objects to numpy datetime 64. """

    def test_simple(self):
        """ Test converting simple UTCDateTimable things """
        test_input = ("2019-01-10 11-12", obspy.UTCDateTime("2019-01-10T12-12"), 100)
        expected = np.array([obspy.UTCDateTime(x)._ns for x in test_input])
        out = np.array(to_datetime64(test_input)).astype(int)
        assert np.equal(expected, out).all()

    def test_with_nulls(self):
        """ Test for handling nulls. """
        test_input = (np.NaN, None, "", 15)
        out = np.array(to_datetime64(test_input))
        # first make sure empty values worked
        assert pd.isnull(out[:3]).all()
        assert out[-1].astype(int) == obspy.UTCDateTime(15)._ns

    def test_zero(self):
        """ Tests for input values as 0 or 0.0 """
        dt1 = to_datetime64(0)
        dt2 = to_datetime64(0.0)
        assert dt1.astype(int) == dt2.astype(int) == 0

    def test_npdatetime64_as_input(self):
        """ This should also work on np.datetime64. """
        test_input = np.array((np.datetime64(1000, "s"), np.datetime64(100, "ns")))
        out = to_datetime64(test_input)
        assert isinstance(out, np.ndarray)
        assert (test_input == out).all()

    def test_pandas_timestamp(self):
        """ Timestamps should also work. """
        kwargs = dict(year=2019, month=10, day=11, hour=12)
        ts = pd.Timestamp(**kwargs)
        out = to_datetime64((ts,))
        expected_out = (ts.to_datetime64(),)
        assert out == expected_out

    def test_utc_to_large(self):
        too_big = obspy.UTCDateTime("2600-01-01")
        with pytest.warns(UserWarning):
            out = to_datetime64(too_big)
        assert pd.Timestamp(out).year == 2262

    def test_series_to_datetimes(self):
        """ Series should be convertible to datetimes, but returns ndarray """
        ser = pd.Series([10, "2010-01-01"])
        out = to_datetime64(ser)
        assert isinstance(out, np.ndarray)


class TestToUTC:
    """ Tests for converting things to UTCDateTime objects. """

    # setup for test values
    utc1 = obspy.UTCDateTime("2019-01-10T12-12")
    utc_list = [utc1, utc1 + 2, utc1 + 3]
    dt64 = np.datetime64(1000, "ns")
    utc_able_list = [1, "2019-02-01", dt64]
    utc_values = [
        0,
        1_000_000,
        "2015-12-01",
        utc1,
        dt64,
        utc_list,
        np.array(utc_list),
        utc_able_list,
        np.array(utc_able_list, dtype=object),
        pd.Series(utc_able_list),
    ]

    @pytest.mark.parametrize("value", utc_values)
    def test_single_value(self, value):
        out = to_utc(value)
        # either a sequence or UTCDateTime should be returned
        assert isinstance(out, (Sequence, UTCDateTime, np.ndarray))


class TestDistanceDataframe:
    """
    Tests for returning a distance dataframe from some number of events
    and some number of stations.
    """

    @pytest.fixture(scope="class")
    def cat(self):
        """ return the first 3 events from the crandall dataset. """
        return obspy.read_events()

    @pytest.fixture(scope="class")
    def inv(self):
        return obspy.read_inventory()

    @pytest.fixture(scope="class")
    def distance_df(self, cat, inv):
        """ Return a dataframe from all the crandall events and stations. """
        return get_distance_df(entity_1=cat, entity_2=inv)

    def test_type(self, distance_df):
        """ ensure a dataframe was returned. """
        assert isinstance(distance_df, pd.DataFrame)
        assert set(distance_df.columns) == set(DISTANCE_COLUMNS)

    def test_all_events_in_df(self, distance_df, cat):
        """ Ensure all the events are in the distance dataframe. """
        event_ids_df = set(distance_df.index.to_frame()["id1"])
        event_ids_cat = {str(x.resource_id) for x in cat}
        assert event_ids_cat == event_ids_df

    def test_all_seed_id_in_df(self, distance_df, inv):
        seed_id_stations = set(obsplus.stations_to_df(inv)["seed_id"])
        seed_id_df = set(distance_df.index.to_frame()["id2"])
        assert seed_id_df == seed_id_stations

    def test_cat_cat(self, cat):
        """ ensure it works with two catalogs """
        df = get_distance_df(cat, cat)
        event_ids = {str(x.resource_id) for x in cat}
        combinations = set(itertools.permutations(event_ids, 2))
        assert combinations == set(df.index)

    def test_dataframe_input(self, cat):
        """
        Any dataframe should be valid input provided it has the required columns.
        """
        data = [[10.1, 10.1, 0, "some_id"]]
        cols = ["latitude", "longitude", "elevation", "id"]
        df = pd.DataFrame(data, columns=cols)
        dist_df = get_distance_df(df, cat)
        # make sure output has expected shape and ids
        assert len(dist_df) == len(cat) * len(df)
        id1 = dist_df.index.get_level_values("id1")
        assert "some_id" in set(id1)


class TestMD5:
    """ Tests for getting md5 hashes from files. """

    @pytest.fixture(scope="class")
    def directory_md5(self, tmpdir_factory):
        """ Create an MD5 directory for testing. """
        td = Path(tmpdir_factory.mktemp("md5test"))
        with (td / "file1.txt").open("w") as fi:
            fi.write("test1")
        subdir = td / "subdir"
        subdir.mkdir(exist_ok=True, parents=True)
        with (subdir / "file2.txt").open("w") as fi:
            fi.write("test2")
        return td

    @pytest.fixture(scope="class")
    def md5_out(self, directory_md5):
        """ return the md5 of the directory. """
        return obsplus.utils.misc.md5_directory(directory_md5, exclude="*1.txt")

    def test_files_exist(self, md5_out):
        """ make sure the hashes exist for the files and such """
        # the file1.txt should not have been included
        assert len(md5_out) == 1
        assert "file1.txt" not in md5_out