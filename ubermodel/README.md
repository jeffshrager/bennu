# Methane Destruction Cost Model (`ubermodel.py`)

A Python model estimating the cost and carbon-credit revenue of photo-catalytic
CH₄ (methane) destruction across three deployment scenarios, plus a global
tropospheric scale-up analysis.  Translated from `Cost_of_methane_destruction.xlsx`.

---

## Scenarios and `--setting`

Each named setting is a pre-configured bundle of background parameters for one
deployment context.  Pass it with `--setting <name>`:

| Setting | Description |
|---|---|
| `ship` | Devices mounted on ocean-going vessels destroying ambient CH₄ |
| `solar` | Dedicated ground-mount solar farm powering CH₄ destruction at ambient concentration |
| `landfill` | Solar panels on a landfill; high local CH₄ concentration (~500 ppm) boosts conversion rate |
| `troposphere` | Back-of-envelope global scale: energy and cost to shift atmospheric CH₄ by 1 ppm |
| `all` | **All four scenarios combined (default)** |

### What `--setting all` does

`all` is not just a shortcut for "run everything" — it also determines which
parameter columns appear in the TSV output.  Specifically:

- It merges the parameter bundles from all four scenarios into one flat dict.
- It runs all four `compute_*()` functions and collects all their outputs.
- The TSV therefore contains every parameter and every output column in one row.

When you run a **single** setting (e.g. `--setting solar`), only that scenario's
parameters and outputs appear in the TSV.  This keeps the file clean when you are
doing a focused sweep and don't want the other scenarios' columns as noise.

When you run `--setting all`, a parameter override applies to every scenario that
uses that parameter.  For example, `--I_ch4_per_kwy 4.5` will affect ship,
solar, landfill, and troposphere outputs simultaneously.

---

## Quick start

```bash
# Run all scenarios with default parameters
python3 ubermodel.py

# Run a single scenario
python3 ubermodel.py --setting solar
python3 ubermodel.py --setting landfill

# Override a primary input (I_ prefix)
python3 ubermodel.py --setting all --I_ch4_per_kwy 4.5

# Override a background setting (B_ prefix)
python3 ubermodel.py --setting solar --B_solar_nameplate_mw 200

# Sweep a parameter over a range [low, high, step]
python3 ubermodel.py --setting solar --B_solar_nameplate_mw '[50,200,50]'

# Sweep multiple parameters (Cartesian product — one row per combination)
python3 ubermodel.py --setting all --I_ch4_per_kwy '[1,5,1]' --I_co2e_ratio '[20,30,5]'
```

> **Shell note:** quote range arguments to prevent glob expansion, e.g. `'[50,200,50]'`.

Results are printed to the terminal and written to `results/results_<setting>_<YYYYMMDD_HHMMSS>.tsv`.

---

## Parameter naming convention

All parameters and computed values carry a two-letter prefix indicating their role:

| Prefix | Meaning | Set by user? |
|---|---|---|
| `I_` | **Primary input** — physical constant or experimental measurement | Yes — the main knobs |
| `B_` | **Background value** — scenario engineering/economic parameter | Rarely; stable defaults |
| `P_` | **Partial result** — intermediate computed value | Never |
| `O_` | **Primary output** — final reported result | Never |

CLI overrides use the full prefixed name:

```bash
--I_ch4_per_kwy 4.5
--B_solar_nameplate_mw '[50,200,50]'
```

### Complete parameter rename table

| Old name (pre-prefix) | New name | Tier |
|---|---|---|
| `ch4_per_kwy` | `I_ch4_per_kwy` | I — primary input |
| `co2e_ratio` | `I_co2e_ratio` | I — primary input |
| `ch4_reference_concentration_ppb` | `I_ch4_reference_concentration_ppb` | I — primary input |
| `credit_price_per_tonne_ch4` | `I_credit_price_per_tonne_ch4` | I — primary input |
| `credit_price_per_tonne_co2e` | `I_credit_price_per_tonne_co2e` | I — primary input |
| `ship_powerplant_mw` | `B_ship_powerplant_mw` | B — background |
| `ship_device_power_kw` | `B_ship_device_power_kw` | B — background |
| `ship_days_per_year` | `B_ship_days_per_year` | B — background |
| `energy_cost_ship_per_kwh` | `B_energy_cost_ship_per_kwh` | B — background |
| `global_ship_fleet` | `B_global_ship_fleet` | B — background |
| `plausible_equipped_fleet` | `B_plausible_equipped_fleet` | B — background |
| `avg_power_per_ship_mw` | `B_avg_power_per_ship_mw` | B — background |
| `solar_nameplate_mw` | `B_solar_nameplate_mw` | B — background |
| `solar_cap_cost_per_mw_nameplate` | `B_solar_cap_cost_per_mw_nameplate` | B — background |
| `solar_land_use_acres_per_mw` | `B_solar_land_use_acres_per_mw` | B — background |
| `solar_nameplate_ratio` | `B_solar_nameplate_ratio` | B — background |
| `solar_panel_lifetime_years` | `B_solar_panel_lifetime_years` | B — background |
| `energy_cost_usa_per_mwh` | `B_energy_cost_usa_per_mwh` | B — background |
| `target_megatonnes` | `B_target_megatonnes` | B — background |
| `landfill_nameplate_mw` | `B_landfill_nameplate_mw` | B — background |
| `landfill_construction_premium` | `B_landfill_construction_premium` | B — background |
| `landfill_ch4_concentration_ppm` | `B_landfill_ch4_concentration_ppm` | B — background |
| `troposphere_volume_m3` | `B_troposphere_volume_m3` | B — background |
| `wh_to_remove_1ppm_per_m3` | `B_wh_to_remove_1ppm_per_m3` | B — background |
| `nuclear_plant_output_wy` | `B_nuclear_plant_output_wy` | B — background |
| `led_efficiency_multiplier` | `B_led_efficiency_multiplier` | B — background |
| `years_to_run` | `B_years_to_run` | B — background |
| `engineering_improvement` | `B_engineering_improvement` | B — background |
| `cost_per_micronuke` | `B_cost_per_micronuke` | B — background |
| *(ship fraction, energy used, fleet power, …)* | `P_ship_*` | P — partial result |
| *(solar available kW, annual capex, …)* | `P_solar_*` | P — partial result |
| *(landfill available kW, concentration factor, …)* | `P_landfill_*` | P — partial result |
| *(Wh/Wy to remove 1 ppm, solar Wy required)* | `P_*_troposphere`, `P_solar_wy_required` | P — partial result |
| *(tonnes converted, revenue, net $, cost/tonne, …)* | `O_ship_*`, `O_solar_*`, `O_landfill_*` | O — output |
| *(nukes needed, total cost, annual cost, …)* | `O_nukes_*`, `O_total_cost`, `O_annual_cost`, … | O — output |

---

## Parameters by setting

### I_ Primary inputs (scenario-independent)

| Parameter | Default | Units | Description |
|---|---|---|---|
| `I_ch4_per_kwy` | 3.0 | t CH₄ / kWy | CH₄ destroyed per kWy of device energy at the reference concentration |
| `I_co2e_ratio` | 28 | — | 100-year global warming potential of CH₄ vs CO₂ |
| `I_ch4_reference_concentration_ppb` | 2 000 | ppb | Concentration at which `I_ch4_per_kwy` was measured |
| `I_credit_price_per_tonne_ch4` | 1 200 | $/t CH₄ | EPA Methane Fee 2025 |
| `I_credit_price_per_tonne_co2e` | 100 | $/t CO₂e | Voluntary carbon market target |

### B_ Ship setting

| Parameter | Default | Units | Description |
|---|---|---|---|
| `B_ship_powerplant_mw` | 60 | MW | Typical ship propulsion power |
| `B_ship_device_power_kw` | 100 | kW | Power allocated to the CH₄ destruction device |
| `B_ship_days_per_year` | 250 | days | Days at sea per year |
| `B_energy_cost_ship_per_kwh` | 0.25 | $/kWh | Shipboard electricity cost |
| `B_global_ship_fleet` | 80 000 | vessels | Total ocean-going vessel count |
| `B_plausible_equipped_fleet` | 10 000 | vessels | Vessels plausibly fitted with devices |
| `B_avg_power_per_ship_mw` | 1 | MW | Device power per equipped ship |

### B_ Solar setting

| Parameter | Default | Units | Description |
|---|---|---|---|
| `B_solar_nameplate_mw` | 100 | MW | Solar field nameplate capacity |
| `B_solar_cap_cost_per_mw_nameplate` | 1 000 000 | $/MW | Installed cost (~$1/W, USA) |
| `B_solar_land_use_acres_per_mw` | 4 | acres/MW | Land requirement |
| `B_solar_nameplate_ratio` | 0.40 | — | Capacity factor (actual output / nameplate) |
| `B_solar_panel_lifetime_years` | 25 | years | Assumed panel service life |
| `B_energy_cost_usa_per_mwh` | 30.0 | $/MWh | USA wholesale electricity (reference only) |
| `B_target_megatonnes` | 100 | Mt CH₄/yr | Climate-policy removal target |

### B_ Landfill setting

| Parameter | Default | Units | Description |
|---|---|---|---|
| `B_landfill_nameplate_mw` | 100 | MW | Landfill solar field nameplate |
| `B_landfill_construction_premium` | 4 | × | Capex multiplier vs standard solar |
| `B_landfill_ch4_concentration_ppm` | 500 | ppm | Local CH₄ concentration (EPA threshold) |
| *(shares `B_solar_cap_cost_per_mw_nameplate`, `B_solar_land_use_acres_per_mw`, `B_solar_nameplate_ratio`, `B_solar_panel_lifetime_years`)* | | | |

### B_ Troposphere setting

| Parameter | Default | Units | Description |
|---|---|---|---|
| `B_troposphere_volume_m3` | 1 × 10¹⁸ | m³ | Approximate troposphere volume |
| `B_wh_to_remove_1ppm_per_m3` | 50 | Wh | Energy to remove 1 ppm CH₄ from 1 m³ of air |
| `B_nuclear_plant_output_wy` | 30 000 000 | Wy | Annual output of one nuclear plant |
| `B_led_efficiency_multiplier` | 1 000 | × | LED devices vs incandescent bulbs |
| `B_years_to_run` | 10 | years | Campaign time horizon |
| `B_engineering_improvement` | 10 | × | Additional device improvement factor |
| `B_cost_per_micronuke` | 20 000 000 | $ | Capital cost of one micro-reactor |
| `B_target_megatonnes` | 100 | Mt CH₄/yr | Climate-policy removal target |

---

## Outputs

Each run prints results to the terminal and saves a tab-separated file to `results/`.

### TSV columns

`setting` | all `I_` and `B_` parameter columns | all `P_` partial results | all `O_` output columns

### Key outputs (by scenario)

**Ship** (`O_` outputs)
`O_ship_ch4_converted_tonnes`, `O_ship_co2e_converted_tonnes`,
`O_ship_revenue_ch4`, `O_ship_revenue_co2e`,
`O_ship_net_ch4`, `O_ship_net_co2e`,
`O_ship_cost_per_tonne_ch4`, `O_ship_cost_per_tonne_co2e`,
`O_fleet_ch4_converted_tonnes`, `O_fleet_co2e_converted_tonnes`, `O_fleet_total_net_co2e`

**Solar** (`O_` outputs)
`O_solar_acreage`, `O_solar_ch4_converted_tonnes`, `O_solar_co2e_converted_tonnes`,
`O_solar_revenue_ch4`, `O_solar_revenue_co2e`, `O_solar_net_ch4`, `O_solar_net_co2e`,
`O_solar_cost_per_tonne_ch4`, `O_solar_cost_per_tonne_co2e`,
`O_solar_nameplate_for_target_mw`, `O_solar_acreage_for_target`

**Landfill** (`O_` outputs)
`O_landfill_acreage`, `O_landfill_ch4_converted_tonnes`, `O_landfill_co2e_converted_tonnes`,
`O_landfill_revenue_ch4`, `O_landfill_revenue_co2e`, `O_landfill_net_ch4`, `O_landfill_net_co2e`,
`O_landfill_cost_per_tonne_ch4`, `O_landfill_cost_per_tonne_co2e`, `O_landfill_capital_cost`

**Troposphere** (`O_` outputs)
`O_nukes_needed`, `O_nukes_with_improvements`,
`O_total_cost`, `O_annual_cost`, `O_solar_w_per_year`

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
- `I_ch4_per_kwy` is treated as linear with CH₄ concentration relative to
  `I_ch4_reference_concentration_ppb`.  The landfill scenario exploits this linearity
  to scale up performance at 500 ppm vs the 2 ppb ambient reference.
- Solar and landfill costs are based on amortized capital expenditure
  (capex ÷ panel lifetime); there are no ongoing fuel costs for solar energy.
- The ship fleet model uses a rough estimate of 10 000 equipped vessels at 1 MW
  each as a plausibility ceiling, not a deployment plan.
- The troposphere numbers are an order-of-magnitude sanity check, not an
  engineering design.
