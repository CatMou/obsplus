"""
tests for get stations
"""
import obspy
import pytest

import obsplus


@pytest.fixture
def inventory():
    return obspy.read_inventory()


class TestGetStation:
    def test_inv_has_get_stations(self, inventory):
        """ get stations should have been monkey patched to stations """
        assert hasattr(inventory, "get_stations")

    def test_return_type(self, inventory):
        """ ensure an stations type is returned """
        assert isinstance(inventory.get_stations(), obspy.Inventory)

    def test_filter_on_lat_lon(self, inventory):
        """ ensure stations can be filtered on lat/lon """
        lat = 48.162899
        lon = 11.275200
        kwargs = dict(
            minlatitude=lat - 0.01,
            maxlatitude=lat + 0.01,
            minlongitude=lon - 0.01,
            maxlongitude=lon + 0.01,
        )
        inv = inventory.get_stations(**kwargs)
        df = obsplus.stations_to_df(inv)
        assert set(df.station) == {"FUR"}

    def test_filter_station(self, inventory):
        """ ensure stations can be filtered """
        inv = inventory.get_stations(station="WET")
        df = obsplus.stations_to_df(inv)
        assert set(df.station) == {"WET"}

    def test_filter_channel_single_wild(self, inventory):
        """ ensure filtering can be done on str attrs with ? """
        inv = inventory.get_stations(channel="HH?")
        df = obsplus.stations_to_df(inv)
        assert all([x.startswith("HH") for x in set(df.channel)])

    def test_filter_channel_star_wild(self, inventory):
        """ ensure filtering can be done with * """
        inv = inventory.get_stations(channel="*z")
        df = obsplus.stations_to_df(inv)
        assert all([x.endswith("Z") for x in set(df.channel)])
