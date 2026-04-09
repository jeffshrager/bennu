#!/usr/bin/env bash
# run.sh — exercise ubermodel.py across a range of functionality
# Each block is labelled with what it tests.  Run with:  bash run.sh

set -euo pipefail
PY=python3
M=ubermodel.py

banner() { echo; echo "══════════════════════════════════════════════════════"; echo "  $*"; echo "══════════════════════════════════════════════════════"; }

# ── 1. Default run: all canonical combos, fluorescent, no overrides ───────────
banner "1. Default run (--setting all)"
$PY $M

# ── 2. Individual settings, default power and device ─────────────────────────
banner "2a. Single setting: ship"
$PY $M --expname test_ship --setting ship

banner "2b. Single setting: field"
$PY $M --expname test_field --setting field

banner "2c. Single setting: landfill"
$PY $M --expname test_landfill --setting landfill

banner "2d. Single setting: troposphere (nuclear, default)"
$PY $M --expname test_tropo_nuclear --setting troposphere

# ── 3. Non-default power sources ─────────────────────────────────────────────
banner "3a. Troposphere + solar power"
$PY $M --expname test_tropo_solar --setting troposphere --power solar

banner "3b. All canonical combos but override troposphere power to solar"
# (ship+solar is unsupported → should warn and skip; others run)
$PY $M --expname test_all_solar --setting all --power solar || true

# ── 4. Device selection ───────────────────────────────────────────────────────
banner "4a. LED device, single setting (ship)"
$PY $M --expname test_ship_led --setting ship --device led

banner "4b. LED device across all canonical combos"
$PY $M --expname test_all_led --setting all --device led

banner "4c. Troposphere + nuclear + LED  (should give ~1.9e3 nukes)"
$PY $M --expname test_tropo_nuke_led --setting troposphere --device led

# ── 5. Single-parameter overrides ────────────────────────────────────────────
banner "5a. Override a primary input: I_ch4_per_kwy = 6.0"
$PY $M --expname test_high_ch4rate --setting all --I_ch4_per_kwy 6.0

banner "5b. Override a background value: larger solar field (500 MW)"
$PY $M --expname test_big_solar --setting field --B_solar_nameplate_mw 500

banner "5c. Override credit price"
$PY $M --expname test_highprice --setting field --I_credit_price_per_tonne_ch4 2000

banner "5d. Override landfill CH4 concentration"
$PY $M --expname test_landfill_highconc --setting landfill \
    --B_landfill_ch4_concentration_ppm 2000

# ── 6. Single-parameter range sweeps ─────────────────────────────────────────
banner "6a. Sweep I_ch4_per_kwy over [1, 5, 1] — field scenario"
$PY $M --expname sweep_ch4rate --setting field --I_ch4_per_kwy '[1,5,1]'

banner "6b. Sweep solar nameplate MW over [50, 300, 50]"
$PY $M --expname sweep_solar_mw --setting field --B_solar_nameplate_mw '[50,300,50]'

banner "6c. Sweep landfill CH4 concentration [100, 1000, 100]"
$PY $M --expname sweep_landfill_conc --setting landfill \
    --B_landfill_ch4_concentration_ppm '[100,1000,100]'

banner "6d. Sweep carbon credit price [500, 2000, 500]"
$PY $M --expname sweep_credit_price --setting field \
    --I_credit_price_per_tonne_ch4 '[500,2000,500]'

banner "6e. Sweep device efficiency on troposphere+nuclear [1,1000,100]"
$PY $M --expname sweep_device_eff --setting troposphere \
    --B_device_efficiency_multiplier '[1,1000,100]'

# ── 7. Multi-parameter Cartesian-product sweeps ───────────────────────────────
banner "7a. 2-param sweep: I_ch4_per_kwy x B_solar_nameplate_mw  (3×3 = 9 rows)"
$PY $M --expname sweep_2param_field --setting field \
    --I_ch4_per_kwy '[1,3,1]' \
    --B_solar_nameplate_mw '[50,150,50]'

banner "7b. 2-param sweep: credit price x co2e ratio  (3×3 = 9 rows, all combos)"
$PY $M --expname sweep_prices_all --setting all \
    --I_credit_price_per_tonne_ch4 '[600,1200,300]' \
    --I_co2e_ratio '[20,28,4]'

banner "7c. 3-param sweep: ch4 rate x solar MW x credit price  (2×2×2 = 8 rows)"
$PY $M --expname sweep_3param --setting field \
    --I_ch4_per_kwy '[2,4,2]' \
    --B_solar_nameplate_mw '[100,200,100]' \
    --I_credit_price_per_tonne_ch4 '[1000,1500,500]'

# ── 8. Named experiments (meaningful expname) ─────────────────────────────────
banner "8a. Named experiment: baseline"
$PY $M --expname baseline

banner "8b. Named experiment: optimistic LED scenario"
$PY $M --expname optimistic_led --setting all --device led \
    --I_ch4_per_kwy 5.0 --I_credit_price_per_tonne_ch4 1500

banner "8c. Named experiment: tundra solar deployment"
$PY $M --expname tundra_solar --setting troposphere --power solar --device led \
    --B_solar_nameplate_ratio 0.25

# ── 9. Verify output files exist and have expected row counts ─────────────────
banner "9. Sanity-check output file row counts (data rows, excluding # headers)"
for f in test_ship test_field test_landfill sweep_ch4rate sweep_2param_field sweep_3param; do
    path="results/${f}.tsv"
    rows=$(grep -c $'^[^\#]' "$path" || true)   # count non-comment lines (header + data)
    data=$(( rows - 1 ))                          # subtract TSV header line
    echo "  $path : $data data row(s)"
done

echo
echo "All tests completed.  Results are in results/"
