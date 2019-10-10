"""
Script to iterate all ObsPlus datasets and delete corresponding indices.
"""

from pathlib import Path

import obsplus

SOURCE_PATHS = [f"{x}_path" for x in ["event", "station", "waveform"]]

if __name__ == "__main__":
    # first load the dataset entry points
    obsplus.DataSet._load_dataset_entry_points()
    for name in obsplus.DataSet._entry_points:
        ds = obsplus.load_dataset(name)
        for source_path in SOURCE_PATHS:
            path = Path(getattr(ds, source_path))
            for index in path.rglob(".index.*"):
                index.unlink()
