import pandas as pd
import numpy as np


def test_sum_level_vs_groupby():
    """Test that df.sum(level=0, axis=1) produces the same result as df.groupby(level=0, axis=1).sum()"""
    # Create sample DataFrames with MultiIndex columns to simulate merged joint data
    arrays = [['Load', 'Load', 'Solar', 'Solar'], ['zone1', 'zone2', 'zone1', 'zone2']]
    tuples = list(zip(*arrays))
    index = pd.MultiIndex.from_tuples(tuples, names=['asset', 'zone'])
    data = np.random.randn(10, 4)  # 10 time steps, 4 columns
    df = pd.DataFrame(data, columns=index)

    # Method 1: Using deprecated sum with level
    result_level = df.sum(level=0, axis=1)

    # Method 2: Using groupby
    result_groupby = df.groupby(level=0, axis=1).sum()

    # Assert they are equal
    pd.testing.assert_frame_equal(result_level, result_groupby)


if __name__ == "__main__":
    test_sum_level_vs_groupby()
    print("Test passed: sum(level=0, axis=1) equivalent to groupby(level=0, axis=1).sum()")