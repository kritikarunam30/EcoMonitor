# Spike report — real data for the live-watch region

Written by `scripts/spike_ee.py` (plan Phase S). This file is the single source of truth for
Earth Engine asset ids, band names, latency and data availability. Later phases must not use
an id or band that is not confirmed here. Machine-readable copy: `docs/SPIKE_FACTS.json`.

Run at 2026-10-10 07:50 UTC.

## 1. Run

| Item | Value |
|---|---|
| Region | singrauli |
| Bounding box | 82.0, 23.6, 83.4, 24.8 |
| Centroid (lon, lat) | 82.7, 24.2 |
| Analysis centre (mean of the largest plants) | 82.7558, 24.131 |
| Analysis window | 120 km square around the centroid |
| Days analysed | 2026-06-03 to 2026-09-30 (120 days) |
| Earth Engine project | land-emission-monitor |
| Earth Engine quota tier (from the Cloud console) | — |

## 2. Collections

Latency is the time between the newest image over the region and the run.

| Key | Asset id | Resolves | Newest image (UTC) | Latency (days) | Scale (m) | Bands | Error |
|---|---|---|---|---|---|---|---|
| s5p_no2_offl | COPERNICUS/S5P/OFFL/L3_NO2 | yes | 2026-09-30 21:50 | 9.40 | 1113.19 | NO2_column_number_density, tropospheric_NO2_column_number_density, stratospheric_NO2_column_number_density, NO2_slant_column_number_density, tropopause_pressure, absorbing_aerosol_index, cloud_fraction, sensor_altitude, sensor_azimuth_angle, sensor_zenith_angle, solar_azimuth_angle, solar_zenith_angle | — |
| s5p_no2_nrti | COPERNICUS/S5P/NRTI/L3_NO2 | yes | 2026-10-10 05:44 | 0.08 | 1113.19 | NO2_column_number_density, tropospheric_NO2_column_number_density, stratospheric_NO2_column_number_density, NO2_slant_column_number_density, tropopause_pressure, absorbing_aerosol_index, cloud_fraction, sensor_altitude, sensor_azimuth_angle, sensor_zenith_angle, solar_azimuth_angle, solar_zenith_angle | — |
| s5p_so2_offl | COPERNICUS/S5P/OFFL/L3_SO2 | yes | 2026-10-07 11:09 | 2.85 | 1113.19 | SO2_column_number_density, SO2_column_number_density_amf, SO2_slant_column_number_density, absorbing_aerosol_index, cloud_fraction, sensor_azimuth_angle, sensor_zenith_angle, solar_azimuth_angle, solar_zenith_angle, SO2_column_number_density_15km | — |
| s5p_so2_nrti | COPERNICUS/S5P/NRTI/L3_SO2 | yes | 2026-10-09 07:44 | 0.99 | 1113.19 | SO2_column_number_density, SO2_column_number_density_amf, SO2_slant_column_number_density, cloud_fraction, sensor_azimuth_angle, sensor_zenith_angle, solar_azimuth_angle, solar_zenith_angle, SO2_column_number_density_15km | — |
| s5p_ch4_offl | COPERNICUS/S5P/OFFL/L3_CH4 | yes | 2026-10-07 14:32 | 2.71 | 1113.19 | CH4_column_volume_mixing_ratio_dry_air, aerosol_height, aerosol_optical_depth, sensor_azimuth_angle, sensor_zenith_angle, solar_azimuth_angle, solar_zenith_angle, CH4_column_volume_mixing_ratio_dry_air_bias_corrected, CH4_column_volume_mixing_ratio_dry_air_uncertainty | — |
| s5p_aer_ai_offl | COPERNICUS/S5P/OFFL/L3_AER_AI | yes | 2026-10-07 17:55 | 2.57 | 1113.19 | absorbing_aerosol_index, sensor_altitude, sensor_azimuth_angle, sensor_zenith_angle, solar_azimuth_angle, solar_zenith_angle | — |
| s5p_aer_ai_nrti | COPERNICUS/S5P/NRTI/L3_AER_AI | yes | 2026-10-10 05:44 | 0.08 | 1113.19 | absorbing_aerosol_index, sensor_altitude, sensor_azimuth_angle, sensor_zenith_angle, solar_azimuth_angle, solar_zenith_angle | — |
| era5_land_hourly | ECMWF/ERA5_LAND/HOURLY | yes | 2026-10-04 19:00 | 5.52 | 11131.95 | dewpoint_temperature_2m, temperature_2m, skin_temperature, soil_temperature_level_1, soil_temperature_level_2, soil_temperature_level_3, soil_temperature_level_4, lake_bottom_temperature, lake_ice_depth, lake_ice_temperature, lake_mix_layer_depth, lake_mix_layer_temperature, lake_shape_factor, lake_total_layer_temperature, snow_albedo, snow_cover, snow_density, snow_depth, snow_depth_water_equivalent, snowfall, snowmelt, temperature_of_snow_layer, skin_reservoir_content, volumetric_soil_water_layer_1, volumetric_soil_water_layer_2, volumetric_soil_water_layer_3, volumetric_soil_water_layer_4, forecast_albedo, surface_latent_heat_flux, surface_net_solar_radiation, surface_net_thermal_radiation, surface_sensible_heat_flux, surface_solar_radiation_downwards, surface_thermal_radiation_downwards, evaporation_from_bare_soil, evaporation_from_open_water_surfaces_excluding_oceans, evaporation_from_the_top_of_canopy, evaporation_from_vegetation_transpiration, potential_evaporation, runoff, snow_evaporation, sub_surface_runoff, surface_runoff, total_evaporation, u_component_of_wind_10m, v_component_of_wind_10m, surface_pressure, total_precipitation, leaf_area_index_high_vegetation, leaf_area_index_low_vegetation, snowfall_hourly, snowmelt_hourly, surface_latent_heat_flux_hourly, surface_net_solar_radiation_hourly, surface_net_thermal_radiation_hourly, surface_sensible_heat_flux_hourly, surface_solar_radiation_downwards_hourly, surface_thermal_radiation_downwards_hourly, evaporation_from_bare_soil_hourly, evaporation_from_open_water_surfaces_excluding_oceans_hourly, evaporation_from_the_top_of_canopy_hourly, evaporation_from_vegetation_transpiration_hourly, potential_evaporation_hourly, runoff_hourly, snow_evaporation_hourly, sub_surface_runoff_hourly, surface_runoff_hourly, total_evaporation_hourly, total_precipitation_hourly | — |
| era5_hourly | ECMWF/ERA5/HOURLY | yes | 2026-10-03 22:00 | 6.40 | 27829.87 | dewpoint_temperature_2m, temperature_2m, ice_temperature_layer_1, ice_temperature_layer_2, ice_temperature_layer_3, ice_temperature_layer_4, mean_sea_level_pressure, sea_surface_temperature, skin_temperature, surface_pressure, u_component_of_wind_100m, v_component_of_wind_100m, u_component_of_neutral_wind_10m, u_component_of_wind_10m, v_component_of_neutral_wind_10m, v_component_of_wind_10m, instantaneous_10m_wind_gust, mean_boundary_layer_dissipation, mean_convective_precipitation_rate, mean_convective_snowfall_rate, mean_eastward_gravity_wave_surface_stress, mean_eastward_turbulent_surface_stress, mean_evaporation_rate, mean_gravity_wave_dissipation, mean_large_scale_precipitation_fraction, mean_large_scale_precipitation_rate, mean_large_scale_snowfall_rate, mean_northward_gravity_wave_surface_stress, mean_northward_turbulent_surface_stress, mean_potential_evaporation_rate, mean_runoff_rate, mean_snow_evaporation_rate, mean_snowfall_rate, mean_snowmelt_rate, mean_sub_surface_runoff_rate, mean_surface_direct_short_wave_radiation_flux, mean_surface_direct_short_wave_radiation_flux_clear_sky, mean_surface_downward_long_wave_radiation_flux, mean_surface_downward_long_wave_radiation_flux_clear_sky, mean_surface_downward_short_wave_radiation_flux, mean_surface_downward_short_wave_radiation_flux_clear_sky, mean_surface_downward_uv_radiation_flux, mean_surface_latent_heat_flux, mean_surface_net_long_wave_radiation_flux, mean_surface_net_long_wave_radiation_flux_clear_sky, mean_surface_net_short_wave_radiation_flux, mean_surface_net_short_wave_radiation_flux_clear_sky, mean_surface_runoff_rate, mean_surface_sensible_heat_flux, mean_top_downward_short_wave_radiation_flux, mean_top_net_long_wave_radiation_flux, mean_top_net_long_wave_radiation_flux_clear_sky, mean_top_net_short_wave_radiation_flux, mean_top_net_short_wave_radiation_flux_clear_sky, mean_total_precipitation_rate, mean_vertically_integrated_moisture_divergence, clear_sky_direct_solar_radiation_at_surface, downward_uv_radiation_at_the_surface, forecast_logarithm_of_surface_roughness_for_heat, instantaneous_surface_sensible_heat_flux, near_ir_albedo_for_diffuse_radiation, near_ir_albedo_for_direct_radiation, surface_latent_heat_flux, surface_net_solar_radiation, surface_net_solar_radiation_clear_sky, surface_net_thermal_radiation, surface_net_thermal_radiation_clear_sky, surface_sensible_heat_flux, surface_solar_radiation_downward_clear_sky, surface_solar_radiation_downwards, surface_thermal_radiation_downward_clear_sky, surface_thermal_radiation_downwards, toa_incident_solar_radiation, top_net_solar_radiation, top_net_solar_radiation_clear_sky, top_net_thermal_radiation, top_net_thermal_radiation_clear_sky, total_sky_direct_solar_radiation_at_surface, uv_visible_albedo_for_diffuse_radiation, uv_visible_albedo_for_direct_radiation, cloud_base_height, high_cloud_cover, low_cloud_cover, medium_cloud_cover, total_cloud_cover, total_column_cloud_ice_water, total_column_cloud_liquid_water, lake_bottom_temperature, lake_cover, lake_depth, lake_ice_depth, lake_ice_temperature, lake_mix_layer_depth, lake_mix_layer_temperature, lake_shape_factor, lake_total_layer_temperature, evaporation, potential_evaporation, runoff, sub_surface_runoff, surface_runoff, convective_precipitation, convective_rain_rate, instantaneous_large_scale_surface_precipitation_fraction, large_scale_precipitation, large_scale_precipitation_fraction, large_scale_rain_rate, precipitation_type, total_column_rain_water, total_precipitation, convective_snowfall, convective_snowfall_rate_water_equivalent, large_scale_snowfall, large_scale_snowfall_rate_water_equivalent, snow_albedo, snow_density, snow_depth, snow_evaporation, snowfall, snowmelt, temperature_of_snow_layer, total_column_snow_water, soil_temperature_level_1, soil_temperature_level_2, soil_temperature_level_3, soil_temperature_level_4, soil_type, vertical_integral_of_divergence_of_cloud_frozen_water_flux, vertical_integral_of_divergence_of_cloud_liquid_water_flux, vertical_integral_of_divergence_of_geopotential_flux, vertical_integral_of_divergence_of_kinetic_energy_flux, vertical_integral_of_divergence_of_mass_flux, vertical_integral_of_divergence_of_moisture_flux, vertical_integral_of_divergence_of_ozone_flux, vertical_integral_of_divergence_of_thermal_energy_flux, vertical_integral_of_divergence_of_total_energy_flux, vertical_integral_of_eastward_cloud_frozen_water_flux, vertical_integral_of_eastward_cloud_liquid_water_flux, vertical_integral_of_eastward_geopotential_flux, vertical_integral_of_eastward_heat_flux, vertical_integral_of_eastward_kinetic_energy_flux, vertical_integral_of_eastward_mass_flux, vertical_integral_of_eastward_ozone_flux, vertical_integral_of_eastward_total_energy_flux, vertical_integral_of_eastward_water_vapour_flux, vertical_integral_of_energy_conversion, vertical_integral_of_kinetic_energy, vertical_integral_of_mass_of_atmosphere, vertical_integral_of_mass_tendency, vertical_integral_of_northward_cloud_frozen_water_flux, vertical_integral_of_northward_cloud_liquid_water_flux, vertical_integral_of_northward_geopotential_flux, vertical_integral_of_northward_heat_flux, vertical_integral_of_northward_kinetic_energy_flux, vertical_integral_of_northward_mass_flux, vertical_integral_of_northward_ozone_flux, high_vegetation_cover, leaf_area_index_high_vegetation, leaf_area_index_low_vegetation, low_vegetation_cover, type_of_high_vegetation, type_of_low_vegetation, air_density_over_the_oceans, coefficient_of_drag_with_waves, free_convective_velocity_over_the_oceans, maximum_individual_wave_height, mean_direction_of_total_swell, mean_direction_of_wind_waves, mean_period_of_total_swell, mean_period_of_wind_waves, mean_square_slope_of_waves, mean_wave_direction, mean_wave_direction_of_first_swell_partition, mean_wave_direction_of_second_swell_partition, mean_wave_direction_of_third_swell_partition, mean_wave_period, mean_wave_period_based_on_first_moment, mean_wave_period_based_on_first_moment_for_swell, mean_wave_period_based_on_first_moment_for_wind_waves, mean_wave_period_based_on_second_moment_for_swell, mean_wave_period_based_on_second_moment_for_wind_waves, mean_wave_period_of_first_swell_partition, mean_wave_period_of_second_swell_partition, mean_wave_period_of_third_swell_partition, mean_zero_crossing_wave_period, model_bathymetry, normalized_energy_flux_into_ocean, normalized_energy_flux_into_waves, normalized_stress_into_ocean, ocean_surface_stress_equivalent_10m_neutral_wind_direction, ocean_surface_stress_equivalent_10m_neutral_wind_speed, peak_wave_period, period_corresponding_to_maximum_individual_wave_height, significant_height_of_combined_wind_waves_and_swell, significant_height_of_total_swell, significant_height_of_wind_waves, significant_wave_height_of_first_swell_partition, significant_wave_height_of_second_swell_partition, significant_wave_height_of_third_swell_partition, angle_of_sub_gridscale_orography, anisotropy_of_sub_gridscale_orography, benjamin_feir_index, boundary_layer_dissipation, boundary_layer_height, charnock, convective_available_potential_energy, convective_inhibition, duct_base_height, eastward_gravity_wave_surface_stress, eastward_turbulent_surface_stress, forecast_albedo, forecast_surface_roughness, friction_velocity, gravity_wave_dissipation, instantaneous_eastward_turbulent_surface_stress, instantaneous_moisture_flux, instantaneous_northward_turbulent_surface_stress, k_index, land_sea_mask, mean_vertical_gradient_of_refractivity_inside_trapping_layer, minimum_vertical_gradient_of_refractivity_inside_trapping_layer, northward_gravity_wave_surface_stress, northward_turbulent_surface_stress, sea_ice_cover, skin_reservoir_content, slope_of_sub_gridscale_orography, standard_deviation_of_filtered_subgrid_orography, standard_deviation_of_orography, total_column_ozone, total_column_supercooled_liquid_water, total_column_water, total_column_water_vapour, total_totals_index, trapping_layer_base_height, trapping_layer_top_height, u_component_stokes_drift, v_component_stokes_drift, vertical_integral_of_northward_total_energy_flux, vertical_integral_of_northward_water_vapour_flux, vertical_integral_of_potential_and_internal_energy, vertical_integral_of_potential_internal_and_latent_energy, vertical_integral_of_temperature, vertical_integral_of_thermal_energy, vertical_integral_of_total_energy, vertically_integrated_moisture_divergence, volumetric_soil_water_layer_1, volumetric_soil_water_layer_2, volumetric_soil_water_layer_3, volumetric_soil_water_layer_4, wave_spectral_directional_width, wave_spectral_directional_width_for_swell, wave_spectral_directional_width_for_wind_waves, wave_spectral_kurtosis, wave_spectral_peakedness, wave_spectral_skewness, zero_degree_level, wind_gust_since_previous_post_processing_10m, geopotential, maximum_2m_temperature_since_previous_post_processing, maximum_total_precipitation_rate_since_previous_post_processing, minimum_2m_temperature_since_previous_post_processing, minimum_total_precipitation_rate_since_previous_post_processing, divergence_500hPa, divergence_850hPa, fraction_of_cloud_cover_500hPa, fraction_of_cloud_cover_850hPa, ozone_mass_mixing_ratio_500hPa, ozone_mass_mixing_ratio_850hPa, potential_vorticity_500hPa, potential_vorticity_850hPa, relative_humidity_500hPa, relative_humidity_850hPa, specific_cloud_ice_water_content_500hPa, specific_cloud_ice_water_content_850hPa, specific_cloud_liquid_water_content_500hPa, specific_cloud_liquid_water_content_850hPa, specific_humidity_500hPa, specific_humidity_850hPa, specific_rain_water_content_500hPa, specific_rain_water_content_850hPa, specific_snow_water_content_500hPa, specific_snow_water_content_850hPa, temperature_500hPa, temperature_850hPa, u_component_of_wind_500hPa, u_component_of_wind_850hPa, v_component_of_wind_500hPa, v_component_of_wind_850hPa, vertical_velocity_500hPa, vertical_velocity_850hPa, vorticity_500hPa, vorticity_850hPa | — |
| gfs | NOAA/GFS0P25 | yes | 2026-10-10 00:00 | 0.31 | 27799.73 | temperature_2m_above_ground, specific_humidity_2m_above_ground, relative_humidity_2m_above_ground, u_component_of_wind_10m_above_ground, v_component_of_wind_10m_above_ground, total_precipitation_surface, precipitable_water_entire_atmosphere, total_cloud_cover_entire_atmosphere, downward_shortwave_radiation_flux | — |
| s2_sr | COPERNICUS/S2_SR_HARMONIZED | yes | 2026-10-09 05:22 | 1.09 | 60 | B1, B2, B3, B4, B5, B6, B7, B8, B8A, B9, B11, B12, AOT, WVP, SCL, TCI_R, TCI_G, TCI_B, MSK_CLDPRB, MSK_SNWPRB, QA10, QA20, QA60, MSK_CLASSI_OPAQUE, MSK_CLASSI_CIRRUS, MSK_CLASSI_SNOW_ICE | — |
| worldcover | ESA/WorldCover/v200 | yes | 2021-01-01 00:00 | 2108.31 | 9.28 | Map | — |
| worldpop | WorldPop/GP/100m/pop | yes | 2020-01-01 00:00 | 2474.31 | 92.77 | population | — |
| modis_burned | MODIS/061/MCD64A1 | yes | 2026-07-01 00:00 | 101.31 | 463.31 | BurnDate, Uncertainty, QA, FirstDay, LastDay | — |

### Bands chosen per product

| Product | Collection key | Asset id | Band | Cloud band | Note |
|---|---|---|---|---|---|
| no2 | s5p_no2_offl | COPERNICUS/S5P/OFFL/L3_NO2 | tropospheric_NO2_column_number_density | cloud_fraction | — |
| no2_nrti | s5p_no2_nrti | COPERNICUS/S5P/NRTI/L3_NO2 | tropospheric_NO2_column_number_density | cloud_fraction | — |
| so2 | s5p_so2_offl | COPERNICUS/S5P/OFFL/L3_SO2 | SO2_column_number_density | cloud_fraction | — |
| so2_nrti | s5p_so2_nrti | COPERNICUS/S5P/NRTI/L3_SO2 | SO2_column_number_density | cloud_fraction | — |
| ch4 | s5p_ch4_offl | COPERNICUS/S5P/OFFL/L3_CH4 | CH4_column_volume_mixing_ratio_dry_air | — | several bands match /CH4_column_volume_mixing_ratio/; the first was taken |
| aer_ai | s5p_aer_ai_offl | COPERNICUS/S5P/OFFL/L3_AER_AI | absorbing_aerosol_index | — | — |
| aer_ai_nrti | s5p_aer_ai_nrti | COPERNICUS/S5P/NRTI/L3_AER_AI | absorbing_aerosol_index | — | — |

## 3. Sentinel-5P quality filtering

Whether the Level-3 product is already QA-filtered cannot be read from the image metadata alone:
confirm it on the catalog page of each collection and write the answer in the last column.

| Collection key | QA / cloud bands found | Masked share of the window on the newest day | QA already applied in L3? (fill in) |
|---|---|---|---|
| s5p_no2_offl | cloud_fraction | 0.80 | — |
| s5p_no2_nrti | cloud_fraction | — | — |
| s5p_so2_offl | cloud_fraction | 0.48 | — |
| s5p_so2_nrti | cloud_fraction | — | — |
| s5p_ch4_offl | — | — | — |
| s5p_aer_ai_offl | — | — | — |
| s5p_aer_ai_nrti | — | — | — |

## 4. Wind

| Collection key | Heights with u and v bands (m) | Days covered in the window | Image properties | Note |
|---|---|---|---|---|
| era5_hourly | 10, 100 | 120 | hour | — |
| era5_land_hourly | 10 | 120 | hour | — |
| gfs | 10 | 0 | creation_time, forecast_hours, forecast_time | no analysis step at 08:00 UTC; the 06:00 UTC analysis covers 120 days of the window |

### 10 m against the best higher level, at the largest plants (08:00 UTC)

| Collection key | Plant | Low level (m) | High level (m) | Mean speed low (m/s) | Mean speed high (m/s) | Ratio high / low | Samples |
|---|---|---|---|---|---|---|---|
| era5_hourly | Vindhyachal | 10 | 100 | 2.89 | 3.99 | 1.38 | 120 |
| era5_hourly | Sasan UMPP | 10 | 100 | 2.86 | 4.08 | 1.42 | 120 |
| era5_hourly | Rihand Thermal Power Station | 10 | 100 | 2.98 | 3.95 | 1.32 | 120 |

### Copernicus CDS (ERA5 100 m)

| Item | Value |
|---|---|
| dataset | reanalysis-era5-single-levels |
| variables | 100m_u_component_of_wind, 100m_v_component_of_wind |
| seconds for one small request | 55.30 |
| newest day retrieved | 2026-10-04 |
| latency (days), at most | 6 |
| variables in the file | u100, v100 |
| dimensions in the file | {'valid_time': 1, 'latitude': 5, 'longitude': 6} |
| request that worked | {"product_type": ["reanalysis"], "variable": ["100m_u_component_of_wind", "100m_v_component_of_wind"], "year": ["2026"], "month": ["10"], "day": ["04"], "time": ["08:00"], "area": [24.8, 82.0, 23.6, 83.4], "data_format": "netcdf", "download_format": "unarchived"} |
| access | ok |

## 5. Plants used (from OpenStreetMap, largest first)

| Name | Lon | Lat | Capacity (MW) | Fuel |
|---|---|---|---|---|
| Vindhyachal | 82.67 | 24.10 | 4760.00 | coal |
| Sasan UMPP | 82.62 | 23.96 | 3960.00 | coal |
| Rihand Thermal Power Station | 82.79 | 24.03 | 3000.00 | coal |
| Obra Thermal Power Station | 82.98 | 24.45 | 2320.00 | coal |
| Singrauli Super Thermal Power Station | 82.71 | 24.11 | 2000.00 | coal |

## 6. Valid days per month

A day counts when at least the stated share of pixels in the window has a value.

### NO2 (threshold 0.50)

| Month | Days | Days valid | Share valid | Share valid at 0.3 |
|---|---|---|---|---|
| 2025-10 | 31 | 8 | 0.26 | 0.39 |
| 2025-11 | 30 | 27 | 0.90 | 0.90 |
| 2025-12 | 31 | 28 | 0.90 | 0.97 |
| 2026-01 | 31 | 26 | 0.84 | 0.87 |
| 2026-02 | 28 | 25 | 0.89 | 0.93 |
| 2026-03 | 31 | 27 | 0.87 | 0.94 |
| 2026-04 | 30 | 27 | 0.90 | 0.90 |
| 2026-05 | 31 | 28 | 0.90 | 1.00 |
| 2026-06 | 30 | 19 | 0.63 | 0.77 |
| 2026-07 | 31 | 4 | 0.13 | 0.26 |
| 2026-08 | 31 | 3 | 0.10 | 0.16 |
| 2026-09 | 30 | 6 | 0.20 | 0.30 |

### SO2 (threshold 0.50)

| Month | Days | Days valid | Share valid | Share valid at 0.3 |
|---|---|---|---|---|
| 2026-06 | 28 | 17 | 0.61 | 0.71 |
| 2026-07 | 31 | 4 | 0.13 | 0.23 |
| 2026-08 | 31 | 2 | 0.06 | 0.16 |
| 2026-09 | 30 | 7 | 0.23 | 0.33 |

## 7. Null-buffer prototype (NO2)

Rough version of the Phase 4 test: the plants' buffers against equal-size buffers drawn in the ring.

| Item | Value |
|---|---|
| Days in the window | 120 |
| Days with a usable local buffer and enough null buffers | 33 |
| Days with z_bg ≥ threshold | 31 |
| z_bg threshold | 2.00 |
| Median of (local − null median), mol/m² | 1.43e-04 |
| Median null sigma, mol/m² | 1.91e-05 |
| Median z_bg | 7.47 |

## 8. SO2 window prototype

Bootstrap z of the wind-aligned downwind enhancement, per plant and per window.

| Plant | Window end | Valid days | Mean enhancement (mol/m²) | z | 5th percentile | Wind source |
|---|---|---|---|---|---|---|
| Vindhyachal | 2026-09-30 | 6 | 1.92e-04 | 3.66 | 1.24e-04 | era5_hourly 100 m |
| Vindhyachal | 2026-09-02 | 3 | 1.20e-05 | 0.23 | -3.24e-04 | era5_hourly 100 m |
| Vindhyachal | 2026-08-05 | 1 | — | — | — | era5_hourly 100 m |
| Vindhyachal | 2026-07-08 | 10 | 2.74e-04 | 4.83 | 1.81e-04 | era5_hourly 100 m |
| Sasan UMPP | 2026-09-30 | 4 | -1.15e-04 | -0.73 | -3.47e-04 | era5_hourly 100 m |
| Sasan UMPP | 2026-09-02 | 0 | — | — | — | era5_hourly 100 m |
| Sasan UMPP | 2026-08-05 | 2 | 6.14e-05 | 0.60 | -1.67e-04 | era5_hourly 100 m |
| Sasan UMPP | 2026-07-08 | 8 | 7.32e-05 | 1.01 | -3.35e-05 | era5_hourly 100 m |
| Rihand Thermal Power Station | 2026-09-30 | 6 | 7.30e-05 | 0.57 | -1.46e-04 | era5_hourly 100 m |
| Rihand Thermal Power Station | 2026-09-02 | 3 | -1.77e-04 | -0.42 | -5.53e-04 | era5_hourly 100 m |
| Rihand Thermal Power Station | 2026-08-05 | 2 | 4.34e-05 | 0.58 | -1.26e-04 | era5_hourly 100 m |
| Rihand Thermal Power Station | 2026-07-08 | 9 | 1.36e-04 | 3.23 | 7.06e-05 | era5_hourly 100 m |

## 8b. The same prototypes on the last dry season (2025-11-01 to 2026-02-28)

| Item | Value |
|---|---|
| Days in the window | 120 |
| Days with a usable local buffer and enough null buffers | 102 |
| Days with z_bg ≥ threshold | 88 |
| Median of (local − null median), mol/m² | 3.35e-04 |
| Median null sigma, mol/m² | 5.12e-05 |
| Median z_bg | 6.29 |

| Plant | Window end | Valid days | Mean enhancement (mol/m²) | z | 5th percentile | Wind source |
|---|---|---|---|---|---|---|
| Vindhyachal | 2026-02-28 | 25 | 2.58e-04 | 4.09 | 1.60e-04 | era5_hourly 100 m |
| Vindhyachal | 2026-01-31 | 22 | 5.00e-04 | 4.21 | 3.06e-04 | era5_hourly 100 m |
| Vindhyachal | 2026-01-03 | 23 | 5.60e-04 | 5.46 | 3.96e-04 | era5_hourly 100 m |
| Vindhyachal | 2025-12-06 | 28 | 3.93e-04 | 2.75 | 1.37e-04 | era5_hourly 100 m |
| Sasan UMPP | 2026-02-28 | 24 | -4.06e-05 | -0.44 | -2.00e-04 | era5_hourly 100 m |
| Sasan UMPP | 2026-01-31 | 21 | 5.41e-05 | 0.51 | -1.20e-04 | era5_hourly 100 m |
| Sasan UMPP | 2026-01-03 | 23 | -1.68e-04 | -1.46 | -3.55e-04 | era5_hourly 100 m |
| Sasan UMPP | 2025-12-06 | 28 | -2.73e-04 | -2.18 | -4.83e-04 | era5_hourly 100 m |
| Rihand Thermal Power Station | 2026-02-28 | 24 | -5.64e-05 | -0.68 | -1.88e-04 | era5_hourly 100 m |
| Rihand Thermal Power Station | 2026-01-31 | 23 | -1.82e-04 | -1.33 | -4.17e-04 | era5_hourly 100 m |
| Rihand Thermal Power Station | 2026-01-03 | 22 | -1.10e-04 | -0.88 | -3.42e-04 | era5_hourly 100 m |
| Rihand Thermal Power Station | 2025-12-06 | 28 | -2.97e-04 | -2.89 | -4.68e-04 | era5_hourly 100 m |

## 9. Earth Engine timing and quota

| Test | Calls | Rows | Seconds | Error text |
|---|---|---|---|---|
| small reduceRegion calls, one day and one buffer each | 100 | — | 61.30 | — |
| one request, reduceRegions mapped over 90 days x 20 buffers | 1 | — | 40.10 | Too many concurrent aggregations. |
| one request, one reduceRegions over 90 days stacked as bands | 1 | 1800 | 3.20 | — |

## 10. FIRMS and flare sources

| Source | Access | Rows in the last 90 days | Date range available | Largest day range accepted | Columns | Error |
|---|---|---|---|---|---|---|
| VIIRS_SNPP_NRT | yes | 199 | 2026-07-01 to 2026-10-09 | 5 | latitude, longitude, bright_ti4, scan, track, acq_date, acq_time, satellite, instrument, confidence, version, bright_ti5, frp, daynight | — |
| VIIRS_NOAA20_NRT | yes | 185 | 2026-07-01 to 2026-10-10 | 5 | latitude, longitude, bright_ti4, scan, track, acq_date, acq_time, satellite, instrument, confidence, version, bright_ti5, frp, daynight | — |
| VIIRS_SNPP_SP | yes | 0 | 2012-01-20 to 2026-06-30 | 5 | latitude, longitude, bright_ti4, scan, track, acq_date, acq_time, satellite, instrument, confidence, version, bright_ti5, frp, daynight, type | — |

FIRMS key status: { "transaction_limit" : 5000, "current_transactions": 0, "transaction_interval" : "10 minutes" }

### Night-time FIRMS detections near the largest plants (last 90 days)

| Source | Plant | Detections | Nights | Most nights in one window | Same, FRP at or above the minimum | Median FRP (MW) |
|---|---|---|---|---|---|---|
| VIIRS_SNPP_NRT | Vindhyachal | 0 | 0 | 0 | 0 | — |
| VIIRS_SNPP_NRT | Sasan UMPP | 0 | 0 | 0 | 0 | — |
| VIIRS_SNPP_NRT | Rihand Thermal Power Station | 0 | 0 | 0 | 0 | — |
| VIIRS_SNPP_NRT | Obra Thermal Power Station | 0 | 0 | 0 | 0 | — |
| VIIRS_SNPP_NRT | Singrauli Super Thermal Power Station | 0 | 0 | 0 | 0 | — |
| VIIRS_NOAA20_NRT | Vindhyachal | 0 | 0 | 0 | 0 | — |
| VIIRS_NOAA20_NRT | Sasan UMPP | 0 | 0 | 0 | 0 | — |
| VIIRS_NOAA20_NRT | Rihand Thermal Power Station | 0 | 0 | 0 | 0 | — |
| VIIRS_NOAA20_NRT | Obra Thermal Power Station | 0 | 0 | 0 | 0 | — |
| VIIRS_NOAA20_NRT | Singrauli Super Thermal Power Station | 0 | 0 | 0 | 0 | — |
| VIIRS_SNPP_SP | Vindhyachal | 0 | 0 | 0 | 0 | — |
| VIIRS_SNPP_SP | Sasan UMPP | 0 | 0 | 0 | 0 | — |
| VIIRS_SNPP_SP | Rihand Thermal Power Station | 0 | 0 | 0 | 0 | — |
| VIIRS_SNPP_SP | Obra Thermal Power Station | 0 | 0 | 0 | 0 | — |
| VIIRS_SNPP_SP | Singrauli Super Thermal Power Station | 0 | 0 | 0 | 0 | — |

### Annual flare-site files in `data/registry/raw/flares`

| File | Sites | Sites inside the region | Error |
|---|---|---|---|
| 2012-2024-Flare-Volume-Estimates-by-individual-Flare-Location.xlsx | 156397 | 0 | — |

### Nightfire (optional; not tested by the script, fill in by hand)

| Item | Value |
|---|---|
| Nightly files found in `data/raw/nightfire/` | 0 |
| Licence status (granted / applied / no licence yet) | — |
| Versions and dates that could be downloaded by hand | — |

## 11. Suggested decisions

Computed from the numbers above. They are suggestions; the decision is written in section 12.

| Decision | Suggestion | Based on |
|---|---|---|
| Wind chain | History: the highest level that covers the window. Today: the source with the smallest latency. Keep a 10 m source last. | era5_hourly: levels [10, 100] m, 120 window days, latency 6.4 d; era5_land_hourly: levels [10] m, 120 window days, latency 5.52 d; gfs: levels [10] m, 0 window days, latency 0.31 d; CDS ERA5 100 m: access ok, latency at most 6 d |
| Source for today and for history | Near-real-time collections for today when their latency is under 1 day; offline collections for history and re-runs. | s5p_no2_offl 9.4 d, s5p_no2_nrti 0.08 d, s5p_so2_offl 2.85 d, s5p_so2_nrti 0.99 d |
| valid_fraction_min and windows | Keep the threshold. | Oct–Mar months in the window: 77% of days valid at threshold 0.5 |
| SO2 scope (gate G1) | SO2 detector stays. | 5 of 22 plant-windows have z ≥ 2.0, a positive 5th percentile and at least 10 valid days; only 13 windows have that many valid days; largest z 5.46 (recent window and dry season 2025-11-01 to 2026-02-28 together) |
| Flaring source (`flaring.source`) | firms_persistent. | 0 annual flare sites in the region; 0 Nightfire files on disk; plants with at least 3 nights of FRP ≥ 5 MW in a 30-day window: none |
| History requests | Use the batched table call per quarter (get_buffer_timeseries); never one call per day. | small reduceRegion calls, one day and one buffer each: 61.3 s, error: none; one request, reduceRegions mapped over 90 days x 20 buffers: 40.1 s, error: Too many concurrent aggregations.; one request, one reduceRegions over 90 days stacked as bands: 3.2 s, error: none |

## 12. Gate G1 — decided by the team

| Question | Decision |
|---|---|
| Wind chain order (`wind.chain`) | era5_100m_ee, cds_era5_100m, gfs_ee, era5_land_10m_ee. ERA5 at 100 m for history (Earth Engine first, CDS second: same data, the CDS queue is slower); GFS 10 m for the last days; ERA5-Land 10 m as fallback |
| Source for "today" and for history | Near-real-time Sentinel-5P collections for today, offline collections for history and re-runs. schedule.rerun_previous_days raised from 5 to 10 because offline NO2 arrives about 9 days late |
| Does SO2 pass (window z ≥ 2 for the main plants)? If not, SO2 becomes a regional layer. | Yes: the SO2 detector stays, tested per watch unit (cluster), not per plant. Vindhyachal passes in all four dry-season windows. No SO2 detections are expected in the monsoon |
| Are valid days in Oct–Mar ≥ 40 %? If not, which windows are widened? | Yes: 77 % of Oct–Mar days are valid. No window is widened |
| `valid_fraction_min` | 0.5 (unchanged) |
| Flaring source (`flaring.source`) | firms_persistent (unchanged). No night-time detections near the plants and no annual flare site in the region, so flaring is expected to be empty for Singrauli and has low priority |
| Region bbox confirmed? | Yes: [82.0, 23.6, 83.4, 24.8]; the five largest plants are inside |
| Decided on | 2026-10-10, by the project owner, following the suggestions in section 11 |

## Errors during the run

| Section | Error |
|---|---|
| — | — |
