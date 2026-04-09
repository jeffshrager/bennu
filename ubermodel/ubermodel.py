"""
Cost of Methane Destruction Model
==================================
Translated from: Cost_of_methane_destruction.xlsx
Sheets modelled: Calculations Master, Summary Master

Parameter naming convention:
  I_  primary inputs      physical/experimental values; the main user-facing knobs
  B_  background values   scenario settings; stable defaults rarely changed
  P_  partial results     intermediate computed values; never set by the user
  O_  primary outputs     final results reported in the terminal and TSV

Usage:
  python ubermodel.py [--setting SETTING] [--param_name value_or_range ...]

  SETTING  one of: ship, solar, landfill, troposphere, all  (default: all)
  Any I_ or B_ parameter may be overridden (without the prefix in the flag name):
    --I_ch4_per_kwy 4.5
    --B_solar_nameplate_mw '[50,200,50]'   (quote ranges to prevent shell glob)

Examples:
  python ubermodel.py --setting solar
  python ubermodel.py --setting all --I_ch4_per_kwy 4.5
  python ubermodel.py --setting solar --B_solar_nameplate_mw '[50,200,50]'
  python ubermodel.py --setting all --I_ch4_per_kwy '[1,5,1]' --I_co2e_ratio '[20,30,5]'
"""

import argparse
import csv
import itertools
import os
import sys
from datetime import datetime

# =============================================================================
# UNIT DEFINITIONS
# =============================================================================
J    = 1
W    = 1
kW   = 1_000 * W
MW   = 1_000 * kW
Wh   = 3_600 * J
kWh  = kW * Wh
MWh  = MW * Wh
ppm  = 1.0
ppb  = ppm / 1_000
hours_per_year          = 365.25 * 24           # ≈ 8 766 h
sunlight_hours_per_year = hours_per_year / 2
kWy  = kW * hours_per_year * Wh                 # Kilowatt-year in Joules
MWy  = MW * hours_per_year * Wh
tonnes_per_gram         = 1e-6
megatonnes_per_tonne    = 1e-6

# =============================================================================
# I_  PRIMARY INPUTS  (physical / experimental — scenario-independent)
# These are the main knobs users will want to adjust.
# =============================================================================
PRIMARY_INPUTS = {
    # Tonnes CH4 destroyed per kWy of device energy (at I_ch4_reference_concentration_ppb;
    # treated as linear with concentration across 2–50 000 ppm)
    'I_ch4_per_kwy':                     3.0,

    # 100-year global warming potential of CH4 relative to CO2
    'I_co2e_ratio':                      28,

    # Reference CH4 concentration at which I_ch4_per_kwy was measured
    'I_ch4_reference_concentration_ppb': 2_000,   # ppb

    # Carbon credit / fee prices
    'I_credit_price_per_tonne_ch4':      1_200,   # $/tonne CH4  (EPA Methane Fee 2025)
    'I_credit_price_per_tonne_co2e':     100,     # $/tonne CO2e (voluntary market target)
}

# =============================================================================
# B_  SETTINGS  (named scenario parameter bundles)
# These are stable background values; select a bundle with --setting <name>.
# Individual parameters may still be overridden via CLI.
# =============================================================================
SETTINGS = {

    # ── Ship Ambient ──────────────────────────────────────────────────────────
    # Devices mounted on ocean-going vessels, destroying ambient-level CH4.
    'ship': {
        'B_ship_powerplant_mw':       60,       # MW  – typical ship propulsion power
        'B_ship_device_power_kw':     100,      # kW  – power allocated to CH4 device
        'B_ship_days_per_year':       250,      # days at sea per year
        'B_energy_cost_ship_per_kwh': 0.25,    # $/kWh – shipboard electricity
        'B_global_ship_fleet':        80_000,   # total ocean-going vessels
        'B_plausible_equipped_fleet': 10_000,   # vessels plausibly fitted with devices
        'B_avg_power_per_ship_mw':    1,        # MW of device power per equipped ship
    },

    # ── Solar Field Ambient ───────────────────────────────────────────────────
    # Ground-mounted solar farm powering CH4 destruction at ambient concentration.
    'solar': {
        'B_solar_nameplate_mw':              100,        # MW – example field nameplate
        'B_solar_cap_cost_per_mw_nameplate': 1_000_000,  # $/MW installed  (~$1/W, USA)
        'B_solar_land_use_acres_per_mw':     4,          # acres per MW nameplate
        'B_solar_nameplate_ratio':           0.40,       # capacity factor (output/nameplate)
        'B_solar_panel_lifetime_years':      25,         # assumed panel service life
        'B_energy_cost_usa_per_mwh':         30.0,       # $/MWh USA wholesale (reference)
        'B_target_megatonnes':               100,        # Mt CH4/yr climate-policy target
    },

    # ── Landfill Solar Field ──────────────────────────────────────────────────
    # Solar panels on a landfill; high local CH4 concentration boosts conversion.
    'landfill': {
        'B_landfill_nameplate_mw':           100,        # MW – example nameplate
        'B_landfill_construction_premium':   4,          # capex multiplier vs standard solar
        'B_landfill_ch4_concentration_ppm':  500,        # ppm – EPA remediation threshold
        # Shared solar-field parameters
        'B_solar_cap_cost_per_mw_nameplate': 1_000_000,
        'B_solar_land_use_acres_per_mw':     4,
        'B_solar_nameplate_ratio':           0.40,
        'B_solar_panel_lifetime_years':      25,
    },

    # ── Troposphere / Global ──────────────────────────────────────────────────
    # Back-of-envelope scale needed to shift global atmospheric CH4 by 1 ppm.
    'troposphere': {
        'B_troposphere_volume_m3':       1e18,          # m³ – approx troposphere volume
        'B_wh_to_remove_1ppm_per_m3':    50,            # Wh to remove 1 ppm CH4 from 1 m³
        'B_nuclear_plant_output_wy':     30_000_000,    # Wy – annual output of one nuclear plant
        'B_led_efficiency_multiplier':   1_000,         # LED devices ~1000× better than bulbs
        'B_years_to_run':                10,            # campaign time horizon (years)
        'B_engineering_improvement':     10,            # additional device improvement factor
        'B_cost_per_micronuke':          20_000_000,    # $ – capital cost of one micro-reactor
        'B_target_megatonnes':           100,           # Mt CH4/yr climate-policy target
    },
}

# 'all' merges every scenario's defaults (later entries override shared param names)
SETTINGS['all'] = {}
for _s in ('ship', 'solar', 'landfill', 'troposphere'):
    SETTINGS['all'].update(SETTINGS[_s])


# =============================================================================
# COMPUTE FUNCTIONS  (one per scenario)
# Each accepts a flat dict p of all I_ and B_ parameters and returns a dict
# of P_ (intermediate) and O_ (output) values.
# =============================================================================

def compute_ship(p):
    # P_  intermediate values
    ship_fraction_of_year      = p['B_ship_days_per_year'] / 365
    energy_cost_ship_per_kwy   = p['B_energy_cost_ship_per_kwh'] * hours_per_year
    ship_energy_used_kwy       = p['B_ship_device_power_kw'] * ship_fraction_of_year
    ship_energy_cost_per_year  = ship_energy_used_kwy * energy_cost_ship_per_kwy
    fleet_total_power_mw       = p['B_plausible_equipped_fleet'] * p['B_avg_power_per_ship_mw']
    fleet_real_power_mw        = fleet_total_power_mw * ship_fraction_of_year
    # O_  primary outputs
    ch4_converted              = ship_energy_used_kwy * p['I_ch4_per_kwy']
    co2e_converted             = ch4_converted * p['I_co2e_ratio']
    revenue_ch4                = ch4_converted  * p['I_credit_price_per_tonne_ch4']
    revenue_co2e               = co2e_converted * p['I_credit_price_per_tonne_co2e']
    net_ch4                    = revenue_ch4  - ship_energy_cost_per_year
    net_co2e                   = revenue_co2e - ship_energy_cost_per_year
    cost_per_tonne_ch4         = ship_energy_cost_per_year / ch4_converted
    cost_per_tonne_co2e        = ship_energy_cost_per_year / co2e_converted
    fleet_ch4                  = fleet_real_power_mw * 1_000 * p['I_ch4_per_kwy']
    fleet_co2e                 = fleet_ch4 * p['I_co2e_ratio']
    fleet_net_co2e             = fleet_co2e * p['I_credit_price_per_tonne_co2e']
    return {
        'P_ship_fraction_of_year':       ship_fraction_of_year,
        'P_ship_energy_used_kwy':        ship_energy_used_kwy,
        'P_ship_energy_cost_per_year':   ship_energy_cost_per_year,
        'P_fleet_total_power_mw':        fleet_total_power_mw,
        'P_fleet_real_power_mw':         fleet_real_power_mw,
        'O_ship_ch4_converted_tonnes':   ch4_converted,
        'O_ship_co2e_converted_tonnes':  co2e_converted,
        'O_ship_revenue_ch4':            revenue_ch4,
        'O_ship_revenue_co2e':           revenue_co2e,
        'O_ship_net_ch4':                net_ch4,
        'O_ship_net_co2e':               net_co2e,
        'O_ship_cost_per_tonne_ch4':     cost_per_tonne_ch4,
        'O_ship_cost_per_tonne_co2e':    cost_per_tonne_co2e,
        'O_fleet_ch4_converted_tonnes':  fleet_ch4,
        'O_fleet_co2e_converted_tonnes': fleet_co2e,
        'O_fleet_total_net_co2e':        fleet_net_co2e,
    }


def compute_solar(p):
    # P_  intermediate values
    available_kw       = p['B_solar_nameplate_mw'] * 1_000 * p['B_solar_nameplate_ratio']
    energy_used_kwy    = available_kw               # kWy/year (kW × 1 yr)
    annual_capex       = (p['B_solar_nameplate_mw'] * p['B_solar_cap_cost_per_mw_nameplate']
                          / p['B_solar_panel_lifetime_years'])
    cap_cost_per_kwy   = annual_capex / energy_used_kwy
    target_tonnes      = p['B_target_megatonnes'] / megatonnes_per_tonne
    # O_  primary outputs
    acreage            = p['B_solar_nameplate_mw'] * p['B_solar_land_use_acres_per_mw']
    ch4_converted      = energy_used_kwy * p['I_ch4_per_kwy']
    co2e_converted     = ch4_converted * p['I_co2e_ratio']
    revenue_ch4        = ch4_converted  * p['I_credit_price_per_tonne_ch4']
    revenue_co2e       = co2e_converted * p['I_credit_price_per_tonne_co2e']
    net_ch4            = revenue_ch4  - annual_capex
    net_co2e           = revenue_co2e - annual_capex
    cost_per_tonne_ch4 = annual_capex / ch4_converted
    cost_per_tonne_co2e= annual_capex / co2e_converted
    mw_for_target      = (target_tonnes / p['I_ch4_per_kwy']) / (p['B_solar_nameplate_ratio'] * 1_000)
    acres_for_target   = mw_for_target * p['B_solar_land_use_acres_per_mw']
    return {
        'P_solar_available_kw':              available_kw,
        'P_solar_energy_used_kwy':           energy_used_kwy,
        'P_solar_annual_capex':              annual_capex,
        'P_solar_cap_cost_per_kwy':          cap_cost_per_kwy,
        'O_solar_acreage':                   acreage,
        'O_solar_ch4_converted_tonnes':      ch4_converted,
        'O_solar_co2e_converted_tonnes':     co2e_converted,
        'O_solar_revenue_ch4':               revenue_ch4,
        'O_solar_revenue_co2e':              revenue_co2e,
        'O_solar_net_ch4':                   net_ch4,
        'O_solar_net_co2e':                  net_co2e,
        'O_solar_cost_per_tonne_ch4':        cost_per_tonne_ch4,
        'O_solar_cost_per_tonne_co2e':       cost_per_tonne_co2e,
        'O_solar_nameplate_for_target_mw':   mw_for_target,
        'O_solar_acreage_for_target':        acres_for_target,
    }


def compute_landfill(p):
    # P_  intermediate values
    available_kw         = (p['B_landfill_nameplate_mw'] * 1_000
                            * p['B_solar_nameplate_ratio'])
    energy_used_kwy      = available_kw
    annual_capex         = (p['B_landfill_construction_premium']
                            * p['B_landfill_nameplate_mw']
                            * p['B_solar_cap_cost_per_mw_nameplate']
                            / p['B_solar_panel_lifetime_years'])
    cap_cost_per_kwy     = annual_capex / energy_used_kwy
    concentration_factor = (1_000 * p['B_landfill_ch4_concentration_ppm']
                            / p['I_ch4_reference_concentration_ppb'])
    # O_  primary outputs
    acreage              = p['B_landfill_nameplate_mw'] * p['B_solar_land_use_acres_per_mw']
    ch4_converted        = energy_used_kwy * p['I_ch4_per_kwy'] * concentration_factor
    co2e_converted       = ch4_converted * p['I_co2e_ratio']
    revenue_ch4          = ch4_converted  * p['I_credit_price_per_tonne_ch4']
    revenue_co2e         = co2e_converted * p['I_credit_price_per_tonne_co2e']
    net_ch4              = revenue_ch4  - annual_capex
    net_co2e             = revenue_co2e - annual_capex
    cost_per_tonne_ch4   = annual_capex / ch4_converted
    cost_per_tonne_co2e  = annual_capex / co2e_converted
    capital_cost         = (p['B_landfill_construction_premium']
                            * p['B_landfill_nameplate_mw']
                            * p['B_solar_cap_cost_per_mw_nameplate'])
    return {
        'P_landfill_available_kw':           available_kw,
        'P_landfill_energy_used_kwy':        energy_used_kwy,
        'P_landfill_annual_capex':           annual_capex,
        'P_landfill_cap_cost_per_kwy':       cap_cost_per_kwy,
        'P_landfill_concentration_factor':   concentration_factor,
        'O_landfill_acreage':                acreage,
        'O_landfill_ch4_converted_tonnes':   ch4_converted,
        'O_landfill_co2e_converted_tonnes':  co2e_converted,
        'O_landfill_revenue_ch4':            revenue_ch4,
        'O_landfill_revenue_co2e':           revenue_co2e,
        'O_landfill_net_ch4':                net_ch4,
        'O_landfill_net_co2e':               net_co2e,
        'O_landfill_cost_per_tonne_ch4':     cost_per_tonne_ch4,
        'O_landfill_cost_per_tonne_co2e':    cost_per_tonne_co2e,
        'O_landfill_capital_cost':           capital_cost,
    }


def compute_troposphere(p):
    # P_  intermediate values
    wh_total    = p['B_troposphere_volume_m3'] * p['B_wh_to_remove_1ppm_per_m3']
    wy_total    = wh_total / hours_per_year
    solar_wy    = wy_total
    # O_  primary outputs
    nukes               = wy_total / p['B_nuclear_plant_output_wy']
    nukes_improved      = nukes / p['B_led_efficiency_multiplier'] / p['B_engineering_improvement'] / p['B_years_to_run']
    total_cost          = nukes * p['B_cost_per_micronuke']
    annual_cost         = total_cost / p['B_years_to_run']
    solar_w_per_year    = solar_wy / p['B_years_to_run']
    return {
        'P_wh_to_remove_1ppm_troposphere':  wh_total,
        'P_wy_to_remove_1ppm_troposphere':  wy_total,
        'P_solar_wy_required':              solar_wy,
        'O_nukes_needed':                   nukes,
        'O_nukes_with_improvements':        nukes_improved,
        'O_total_cost':                     total_cost,
        'O_annual_cost':                    annual_cost,
        'O_solar_w_per_year':               solar_w_per_year,
    }


SCENARIO_FUNCS = {
    'ship':        compute_ship,
    'solar':       compute_solar,
    'landfill':    compute_landfill,
    'troposphere': compute_troposphere,
}


def run_scenario(setting_name, params):
    outputs = {}
    scenarios = list(SCENARIO_FUNCS.keys()) if setting_name == 'all' else [setting_name]
    for name in scenarios:
        outputs.update(SCENARIO_FUNCS[name](params))
    return outputs


# =============================================================================
# TERMINAL OUTPUT
# =============================================================================

def fmt(v, prefix='$', decimals=2):
    return f'{prefix}{v:,.{decimals}f}' if prefix else f'{v:,.{decimals}f}'


def print_results(setting_name, params, outputs):
    print('=' * 65)
    print('METHANE DESTRUCTION COST MODEL')
    print(f'Setting: {setting_name}')
    print('=' * 65)

    if 'O_ship_ch4_converted_tonnes' in outputs:
        print('\n--- Ship Ambient (single device) ---')
        print(f"  Energy used:                    {outputs['P_ship_energy_used_kwy']:.3f} kWy")
        print(f"  Energy cost/year:              {fmt(outputs['P_ship_energy_cost_per_year'])}")
        print(f"  CH4 converted:                  {outputs['O_ship_ch4_converted_tonnes']:.4f} t CH4")
        print(f"  CO2e converted:                 {outputs['O_ship_co2e_converted_tonnes']:.4f} t CO2e")
        print(f"  Revenue (CH4 credits):         {fmt(outputs['O_ship_revenue_ch4'])}")
        print(f"  Revenue (CO2e credits):        {fmt(outputs['O_ship_revenue_co2e'])}")
        print(f"  Net $ (CH4 basis):             {fmt(outputs['O_ship_net_ch4'])}")
        print(f"  Net $ (CO2e basis):            {fmt(outputs['O_ship_net_co2e'])}")
        print(f"  Cost/tonne CH4:                {fmt(outputs['O_ship_cost_per_tonne_ch4'])}")
        print(f"  Cost/tonne CO2e:               {fmt(outputs['O_ship_cost_per_tonne_co2e'])}")
        print(f"  Fleet CH4/year:                 {outputs['O_fleet_ch4_converted_tonnes']:,.1f} t")
        print(f"  Fleet CO2e/year:                {outputs['O_fleet_co2e_converted_tonnes']:,.1f} t")
        print(f"  Fleet CO2e revenue:            {fmt(outputs['O_fleet_total_net_co2e'])}")

    if 'O_solar_ch4_converted_tonnes' in outputs:
        print('\n--- Solar Field Ambient ---')
        print(f"  Acreage:                        {outputs['O_solar_acreage']:,.0f} acres")
        print(f"  Energy used:                    {outputs['P_solar_energy_used_kwy']:,.0f} kWy")
        print(f"  Annual capex:                  {fmt(outputs['P_solar_annual_capex'])}")
        print(f"  CH4 converted:                  {outputs['O_solar_ch4_converted_tonnes']:,.1f} t CH4")
        print(f"  CO2e converted:                 {outputs['O_solar_co2e_converted_tonnes']:,.1f} t CO2e")
        print(f"  Revenue (CH4):                 {fmt(outputs['O_solar_revenue_ch4'])}")
        print(f"  Revenue (CO2e):                {fmt(outputs['O_solar_revenue_co2e'])}")
        print(f"  Net $ (CH4):                   {fmt(outputs['O_solar_net_ch4'])}")
        print(f"  Net $ (CO2e):                  {fmt(outputs['O_solar_net_co2e'])}")
        print(f"  Cost/tonne CH4:                {fmt(outputs['O_solar_cost_per_tonne_ch4'])}")
        print(f"  Cost/tonne CO2e:               {fmt(outputs['O_solar_cost_per_tonne_co2e'])}")
        print(f"  MW for {params.get('B_target_megatonnes', 100)} Mt target:          "
              f"{outputs['O_solar_nameplate_for_target_mw']:,.0f} MW")

    if 'O_landfill_ch4_converted_tonnes' in outputs:
        print('\n--- Landfill Solar Field ---')
        print(f"  Concentration factor:           {outputs['P_landfill_concentration_factor']:,.0f}x")
        print(f"  Annual capex:                  {fmt(outputs['P_landfill_annual_capex'])}")
        print(f"  CH4 converted:                  {outputs['O_landfill_ch4_converted_tonnes']:,.1f} t CH4")
        print(f"  CO2e converted:                 {outputs['O_landfill_co2e_converted_tonnes']:,.1f} t CO2e")
        print(f"  Revenue (CH4):                 {fmt(outputs['O_landfill_revenue_ch4'])}")
        print(f"  Revenue (CO2e):                {fmt(outputs['O_landfill_revenue_co2e'])}")
        print(f"  Net $ (CH4):                   {fmt(outputs['O_landfill_net_ch4'])}")
        print(f"  Net $ (CO2e):                  {fmt(outputs['O_landfill_net_co2e'])}")
        print(f"  Total capital cost:            {fmt(outputs['O_landfill_capital_cost'])}")

    if 'O_nukes_needed' in outputs:
        print('\n--- Global / Troposphere ---')
        print(f"  Energy to remove 1 ppm:         {outputs['P_wy_to_remove_1ppm_troposphere']:.3e} Wy")
        print(f"  Nuclear plants required:        {outputs['O_nukes_needed']:.3e}")
        print(f"  With LED + engineering:         {outputs['O_nukes_with_improvements']:.3e}")
        print(f"  Total cost:                    {fmt(outputs['O_total_cost'])}")
        print(f"  Annual cost:                   {fmt(outputs['O_annual_cost'])}")
        print(f"  Solar power needed:             {outputs['O_solar_w_per_year']:.3e} W")

    print('=' * 65)


# =============================================================================
# CLI + TSV OUTPUT
# =============================================================================

def parse_range_arg(s):
    """Parse 'nnn' -> [float] or '[low,high,step]' -> [float, ...]."""
    s = s.strip()
    if s.startswith('[') and s.endswith(']'):
        parts = s[1:-1].split(',')
        if len(parts) != 3:
            raise ValueError(f"Range must be [low,high,step], got: {s}")
        low, high, step = float(parts[0]), float(parts[1]), float(parts[2])
        values, v = [], low
        while v <= high + step * 1e-9:
            values.append(round(v, 12))
            v += step
        if not values:
            raise ValueError(f"Empty range: {s}")
        return values
    return [float(s)]


def main():
    parser = argparse.ArgumentParser(
        description='Methane Destruction Cost Model',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument('--setting', default='all',
                        choices=list(SETTINGS.keys()),
                        help='Named parameter bundle (default: all)')
    known, remaining = parser.parse_known_args()
    setting_name = known.setting

    base_params = {**PRIMARY_INPUTS, **SETTINGS[setting_name]}

    # Parse remaining args as --param_name value_or_range pairs
    overrides = {}
    i = 0
    while i < len(remaining):
        tok = remaining[i]
        if not tok.startswith('--'):
            parser.error(f"Unexpected token: {tok!r}")
        param_name = tok[2:]
        if i + 1 >= len(remaining):
            parser.error(f"--{param_name} requires a value")
        try:
            overrides[param_name] = parse_range_arg(remaining[i + 1])
        except ValueError as e:
            parser.error(str(e))
        i += 2

    # Warn about unrecognised parameter names
    known_params = set(PRIMARY_INPUTS) | set(SETTINGS['all'])
    for pname in overrides:
        if pname not in known_params:
            print(f"Warning: '{pname}' is not a recognised parameter name", file=sys.stderr)

    # Cartesian product of all range overrides
    if overrides:
        sweep_names  = list(overrides.keys())
        sweep_combos = list(itertools.product(*[overrides[n] for n in sweep_names]))
    else:
        sweep_names, sweep_combos = [], [()]

    # Compute one result per parameter combination
    results = []
    for combo in sweep_combos:
        p = dict(base_params)
        for name, val in zip(sweep_names, combo):
            p[name] = val
        outputs = run_scenario(setting_name, p)
        results.append((p, outputs))

    # Print to terminal
    for p, outputs in results:
        print_results(setting_name, p, outputs)

    # Write timestamped TSV
    os.makedirs('results', exist_ok=True)
    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
    tsv_path = os.path.join('results', f'results_{setting_name}_{ts}.tsv')

    param_keys  = list(base_params.keys())
    output_keys = list(results[0][1].keys())
    fieldnames  = ['setting'] + param_keys + output_keys

    with open(tsv_path, 'w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter='\t')
        writer.writeheader()
        for p, outputs in results:
            row = {'setting': setting_name}
            row.update({k: p.get(k, '') for k in param_keys})
            row.update(outputs)
            writer.writerow(row)

    n = len(results)
    print(f"\nResults written to: {tsv_path}  ({n} row{'s' if n != 1 else ''})")


if __name__ == '__main__':
    main()
