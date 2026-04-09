# Methane Destruction Cost Model (`ubermodel.py`)

A Python model estimating the cost and carbon-credit revenue of photo-catalytic
CH₄ (methane) destruction across three deployment scenarios, plus a global
tropospheric scale-up analysis.  Translated from `Cost_of_methane_destruction.xlsx`.

---

## Scenarios

| Setting | Description |
|---|---|
| `ship` | Devices mounted on ocean-going vessels destroying ambient CH₄ |
| `solar` | Dedicated ground-mount solar farm powering CH₄ destruction at ambient concentration |
| `landfill` | Solar panels on a landfill; high local CH₄ concentration (~500 ppm) boosts conversion rate |
| `troposphere` | Back-of-envelope global scale: energy and cost to shift atmospheric CH₄ by 1 ppm |
| `all` | All four scenarios combined (default) |

---

## Quick start

```bash
# Run all scenarios with default parameters
python3 ubermodel.py

# Run a single scenario
python3 ubermodel.py --setting solar
python3 ubermodel.py --setting landfill

# Override one parameter
python3 ubermodel.py --setting all --ch4_per_kwy 4.5

# Sweep a parameter over a range [low, high, step]
python3 ubermodel.py --setting solar --solar_nameplate_mw '[50,200,50]'

# Sweep multiple parameters (Cartesian product — one row per combination)
python3 ubermodel.py --setting all --ch4_per_kwy '[1,5,1]' --co2e_ratio '[20,30,5]'
```

> **Shell note:** quote range arguments to prevent glob expansion, e.g. `'[50,200,50]'`.

Results are printed to the terminal and written to `results/results_<setting>_<YYYYMMDD_HHMMSS>.tsv`.

---

## Parameters

### Primary inputs (physical / experimental — scenario-independent)

| Parameter | Default | Units | Description |
|---|---|---|---|
| `ch4_per_kwy` | 3.0 | t CH₄ / kWy | CH₄ destroyed per kWy of device energy at the reference concentration |
| `co2e_ratio` | 28 | — | 100-year global warming potential of CH₄ vs CO₂ |
| `ch4_reference_concentration_ppb` | 2 000 | ppb | Concentration at which `ch4_per_kwy` was measured |
| `credit_price_per_tonne_ch4` | 1 200 | $/t CH₄ | EPA Methane Fee 2025 |
| `credit_price_per_tonne_co2e` | 100 | $/t CO₂e | Voluntary carbon market target |

### Ship setting

| Parameter | Default | Units | Description |
|---|---|---|---|
| `ship_powerplant_mw` | 60 | MW | Typical ship propulsion power |
| `ship_device_power_kw` | 100 | kW | Power allocated to the CH₄ destruction device |
| `ship_days_per_year` | 250 | days | Days at sea per year |
| `energy_cost_ship_per_kwh` | 0.25 | $/kWh | Shipboard electricity cost |
| `global_ship_fleet` | 80 000 | vessels | Total ocean-going vessel count |
| `plausible_equipped_fleet` | 10 000 | vessels | Vessels plausibly fitted with devices |
| `avg_power_per_ship_mw` | 1 | MW | Device power per equipped ship |

### Solar setting

| Parameter | Default | Units | Description |
|---|---|---|---|
| `solar_nameplate_mw` | 100 | MW | Solar field nameplate capacity |
| `solar_cap_cost_per_mw_nameplate` | 1 000 000 | $/MW | Installed cost (~$1/W, USA) |
| `solar_land_use_acres_per_mw` | 4 | acres/MW | Land requirement |
| `solar_nameplate_ratio` | 0.40 | — | Capacity factor (actual output / nameplate) |
| `solar_panel_lifetime_years` | 25 | years | Assumed panel service life |
| `energy_cost_usa_per_mwh` | 30.0 | $/MWh | USA wholesale electricity (reference) |
| `target_megatonnes` | 100 | Mt CH₄/yr | Climate-policy removal target |

### Landfill setting

| Parameter | Default | Units | Description |
|---|---|---|---|
| `landfill_nameplate_mw` | 100 | MW | Landfill solar field nameplate |
| `landfill_construction_premium` | 4 | × | Capex multiplier vs standard solar |
| `landfill_ch4_concentration_ppm` | 500 | ppm | Local CH₄ concentration (EPA threshold) |
| *(shares `solar_cap_cost_per_mw_nameplate`, `solar_land_use_acres_per_mw`, `solar_nameplate_ratio`, `solar_panel_lifetime_years`)* | | | |

### Troposphere setting

| Parameter | Default | Units | Description |
|---|---|---|---|
| `troposphere_volume_m3` | 1 × 10¹⁸ | m³ | Approximate troposphere volume |
| `wh_to_remove_1ppm_per_m3` | 50 | Wh | Energy to remove 1 ppm CH₄ from 1 m³ of air |
| `nuclear_plant_output_wy` | 30 000 000 | Wy | Annual output of one nuclear plant |
| `led_efficiency_multiplier` | 1 000 | × | LED devices vs incandescent bulbs |
| `years_to_run` | 10 | years | Campaign time horizon |
| `engineering_improvement` | 10 | × | Additional device improvement factor |
| `cost_per_micronuke` | 20 000 000 | $ | Capital cost of one micro-reactor |
| `target_megatonnes` | 100 | Mt CH₄/yr | Climate-policy removal target |

---

## Outputs

Each run prints results to the terminal and saves a tab-separated file to `results/`.

### TSV columns

`setting` | all parameter columns (in setting order) | all computed output columns

### Key computed outputs (by scenario)

**Ship**
`ship_energy_used_kwy`, `ship_energy_cost_per_year`, `ship_ch4_converted_tonnes`,
`ship_co2e_converted_tonnes`, `ship_revenue_ch4`, `ship_revenue_co2e`,
`ship_net_ch4`, `ship_net_co2e`, `ship_cost_per_tonne_ch4`, `ship_cost_per_tonne_co2e`,
`fleet_ch4_converted_tonnes`, `fleet_co2e_converted_tonnes`, `fleet_total_net_co2e`

**Solar**
`solar_acreage`, `solar_energy_used_kwy`, `solar_annual_capex`,
`solar_ch4_converted_tonnes`, `solar_co2e_converted_tonnes`,
`solar_revenue_ch4`, `solar_revenue_co2e`, `solar_net_ch4`, `solar_net_co2e`,
`solar_cost_per_tonne_ch4`, `solar_cost_per_tonne_co2e`,
`solar_nameplate_for_target_mw`, `solar_acreage_for_target`

**Landfill**
`landfill_concentration_factor`, `landfill_annual_capex`, `landfill_capital_cost`,
`landfill_ch4_converted_tonnes`, `landfill_co2e_converted_tonnes`,
`landfill_revenue_ch4`, `landfill_revenue_co2e`, `landfill_net_ch4`, `landfill_net_co2e`,
`landfill_cost_per_tonne_ch4`, `landfill_cost_per_tonne_co2e`

**Troposphere**
`wy_to_remove_1ppm_troposphere`, `nukes_needed`, `nukes_with_improvements`,
`total_cost`, `annual_cost`, `solar_w_per_year`

---

## Directory layout

```
ubermodel/
├── ubermodel.py        # model + CLI
├── README.md           # this file
├── results/            # auto-created; timestamped TSV outputs
└── seshsums/           # human-readable session summaries
```

---

## Model notes

- All monetary values are USD.  Mass is metric tonnes.  Energy is SI (Joules) with
  practical aliases (kWh, kWy, MWy).
- `ch4_per_kwy` is treated as linear with CH₄ concentration relative to
  `ch4_reference_concentration_ppb`.  The landfill scenario uses this linearity to
  scale up performance at 500 ppm vs the 2 ppb reference.
- Solar and landfill costs are based on amortized capital expenditure
  (capex ÷ panel lifetime); there are no ongoing fuel costs for solar energy.
- The ship fleet model uses a rough estimate of 10 000 equipped vessels at 1 MW
  each as a plausibility ceiling, not a deployment plan.
- The troposphere numbers are an order-of-magnitude sanity check, not an
  engineering design.
