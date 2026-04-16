import pandas as pd
import numpy as np
from pgscen.pca import PCAGeminiEngine
from datetime import datetime, timedelta


def make_time_index(start, periods, freq='H'):
    return pd.date_range(start=start, periods=periods, freq=freq, tz='utc')


def synthetic_site_meta():
    # create minimal solar meta with two sites in different zones
    return pd.DataFrame({
        'Zone': ['Z1', 'Z2'],
        'latitude': [30.0, 31.0],
        'longitude': [-97.0, -96.0],
        'Capacity': [100.0, 120.0]
    }, index=['site1', 'site2'])


def synthetic_load_meta():
    return None


def create_synthetic_actuals_forecasts(n_sites=2, n_hours=24, start='2018-05-11 00:00'):
    idx = make_time_index(start, n_hours)
    # actuals: small diurnal pattern
    actuals = pd.DataFrame({f'site{i+1}': 20 + 10 * np.sin(np.linspace(0, 2*np.pi, n_hours)) for i in range(n_sites)}, index=idx)
    # forecasts: actuals with small noise
    fidx = pd.MultiIndex.from_product([idx, range(1)], names=['Forecast_time', 'H'])
    # For compatibility with PCAGeminiEngine, construct forecast df with Issue_time and Forecast_time columns
    forecasts = pd.DataFrame({
        'Issue_time': [idx[0]] * n_sites,
        'Forecast_time': idx,
    })
    # But PCAGeminiEngine expects a DataFrame with Issue_time and Forecast_time columns and site columns; simplify by building a traditional forecast df
    forecast_df = pd.DataFrame({f'site{i+1}': actuals[f'site{i+1}'] + np.random.randn(n_hours)*0.1 for i in range(n_sites)}, index=idx)
    forecast_df = forecast_df.reset_index().rename(columns={'index': 'Forecast_time'})
    # create same-format historical forecast (with Issue_time)
    hist_fcst = forecast_df.copy()
    hist_fcst['Issue_time'] = hist_fcst['Forecast_time'] - pd.Timedelta(hours=6)

    return actuals, hist_fcst, forecast_df


def test_joint_model_basic():
    # Create small synthetic data
    actuals, hist_fcst, forecast_df = create_synthetic_actuals_forecasts()
    meta = synthetic_site_meta()

    # instantiate engine
    scen_start = pd.to_datetime('2018-05-11 00:00').tz_localize('utc')
    engine = PCAGeminiEngine(actuals, hist_fcst, scen_start, meta)

    # create minimal load history -- use actuals as a stand-in for load
    load_actuals = actuals.copy()
    load_fcst = forecast_df.copy()

    # call fit_load_solar_joint_model with very small model sizes to keep runtime short
    engine.fit_load_solar_joint_model(load_actuals, load_fcst,
                                     load_asset_rho=0.01, load_horizon_rho=0.01,
                                     solar_asset_rho=0.01, solar_pca_comp_rho=0.01,
                                     joint_asset_rho=0.01,
                                     num_of_components=1, nearest_days=5,
                                     use_all_load_hist=False)

    assert engine.joint_md is not None


if __name__ == '__main__':
    test_joint_model_basic()
    print('Joint model test passed')
