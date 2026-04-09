"""
Cost of Methane Destruction Model
==================================
Translated from: Cost_of_methane_destruction.xlsx
Sheets modelled: Calculations Master, Summary Master

Usage:
  python ubermodel.py [--setting SETTING] [--param_name value_or_range ...]

  SETTING  one of: ship, solar, landfill, troposphere, all  (default: all)
  Any parameter may be overridden:
    --param_name 4.5              single value
    --param_name [1.0,5.0,0.5]   sweep; one output row per step

Examples:
  python ubermodel.py --setting solar
  python ubermodel.py --setting all --ch4_per_kwy 4.5
  python ubermodel.py --setting solar --solar_nameplate_mw [50,200,50]
  python ubermodel.py --setting all --ch4_per_kwy [1,5,1] --co2e_ratio [20,30,5]
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
# PRIMARY INPUTS  (physical / experimental — scenario-independent)
# Override any with --param_name value.
# =============================================================================
PRIMARY_INPUTS = {
    # Tonnes CH4 destroyed per kWy of device energy (at ch4_reference_concentration_ppb;
    # treated as linear with concentration across 2–50 000 ppm)
    'ch4_per_kwy':                     3.0,

    # 100-year global warming potential of CH4 relative to CO2
    'co2e_ratio':                      28,

    # Reference CH4 concentration at which ch4_per_kwy was measured
    'ch4_reference_concentration_ppb': 2_000,   # ppb

    # Carbon credit / fee prices
    'credit_price_per_tonne_ch4':      1_200,   # $/tonne CH4  (EPA Methane Fee 2025)
    'credit_price_per_tonne_co2e':     100,     # $/tonne CO2e (voluntary market target)
}

# =============================================================================
# SETTINGS  (named scenario parameter bundles)
# Select with --setting <name>.  Override individual params via --param_name.
# =============================================================================
SETTINGS = {

    # ── Ship Ambient ──────────────────────────────────────────────────────────
    # Devices mounted on ocean-going vessels, destroying ambient-level CH4.
    'ship': {
        'ship_powerplant_mw':       60,       # MW  – typical ship propulsion power
        'ship_device_power_kw':     100,      # kW  – power allocated to CH4 device
        'ship_days_per_year':       250,      # days at sea per year
        'energy_cost_ship_per_kwh': 0.25,    # $/kWh – shipboard electricity
        'global_ship_fleet':        80_000,   # total ocean-going vessels
        'plausible_equipped_fleet': 10_000,   # vessels plausibly fitted with devices
        'avg_power_per_ship_mw':    1,        # MW of device power per equipped ship
    },

    # ── Solar Field Ambient ───────────────────────────────────────────────────
    # Ground-mounted solar farm powering CH4 destruction at ambient concentration.
    'solar': {
        'solar_nameplate_mw':              100,        # MW – example field nameplate
        'solar_cap_cost_per_mw_nameplate': 1_000_000,  # $/MW installed  (~$1/W, USA)
        'solar_land_use_acres_per_mw':     4,          # acres per MW nameplate
        'solar_nameplate_ratio':           0.40,       # capacity factor (output/nameplate)
        'solar_panel_lifetime_years':      25,         # assumed panel service life
        'energy_cost_usa_per_mwh':         30.0,       # $/MWh USA wholesale (reference)
        'target_megatonnes':               100,        # Mt CH4/yr climate-policy target
    },

    # ── Landfill Solar Field ──────────────────────────────────────────────────
    # Solar panels on a landfill; high local CH4 concentration boosts conversion.
    'landfill': {
        'landfill_nameplate_mw':           100,        # MW – example nameplate
        'landfill_construction_premium':   4,          # capex multiplier vs standard solar
        'landfill_ch4_concentration_ppm':  500,        # ppm – EPA remediation threshold
        # Shared solar-field parameters
        'solar_cap_cost_per_mw_nameplate': 1_000_000,
        'solar_land_use_acres_per_mw':     4,
        'solar_nameplate_ratio':           0.40,
        'solar_panel_lifetime_years':      25,
    },

    # ── Troposphere / Global ──────────────────────────────────────────────────
    # Back-of-envelope scale needed to shift global atmospheric CH4 by 1 ppm.
    'troposphere': {
        'troposphere_volume_m3':       1e18,          # m³ – approx troposphere volume
        'wh_to_remove_1ppm_per_m3':    50,            # Wh to remove 1 ppm CH4 from 1 m³
        'nuclear_plant_output_wy':     30_000_000,    # Wy – annual output of one nuclear plant
        'led_efficiency_multiplier':   1_000,         # LED devices ~1000× better than bulbs
        'years_to_run':                10,            # campaign time horizon (years)
        'engineering_improvement':     10,            # additional device improvement factor
        'cost_per_micronuke':          20_000_000,    # $ – capital cost of one micro-reactor
        'target_megatonnes':           100,           # Mt CH4/yr climate-policy target
    },
}

# 'all' merges every scenario's defaults (later entries override shared param names)
SETTINGS['all'] = {}
for _s in ('ship', 'solar', 'landfill', 'troposphere'):
    SETTINGS['all'].update(SETTINGS[_s])


# =============================================================================
# COMPUTE FUNCTIONS  (one per scenario)
# Each accepts a flat dict p of all parameters and returns a dict of outputs.
# =============================================================================

def compute_ship(p):
    ship_fraction_of_year       = p['ship_days_per_year'] / 365
    energy_cost_ship_per_kwy    = p['energy_cost_ship_per_kwh'] * hours_per_year
    ship_energy_used_kwy        = p['ship_device_power_kw'] * ship_fraction_of_year
    ship_energy_cost_per_year   = ship_energy_used_kwy * energy_cost_ship_per_kwy
    ship_ch4_converted_tonnes   = ship_energy_used_kwy * p['ch4_per_kwy']
    ship_co2e_converted_tonnes  = ship_ch4_converted_tonnes * p['co2e_ratio']
    ship_revenue_ch4            = ship_ch4_converted_tonnes  * p['credit_price_per_tonne_ch4']
    ship_revenue_co2e           = ship_co2e_converted_tonnes * p['credit_price_per_tonne_co2e']
    ship_net_ch4                = ship_revenue_ch4  - ship_energy_cost_per_year
    ship_net_co2e               = ship_revenue_co2e - ship_energy_cost_per_year
    ship_cost_per_tonne_ch4     = ship_energy_cost_per_year / ship_ch4_converted_tonnes
    ship_cost_per_tonne_co2e    = ship_energy_cost_per_year / ship_co2e_converted_tonnes
    fleet_total_power_mw        = p['plausible_equipped_fleet'] * p['avg_power_per_ship_mw']
    fleet_real_power_mw         = fleet_total_power_mw * ship_fraction_of_year
    fleet_ch4_converted_tonnes  = fleet_real_power_mw * 1_000 * p['ch4_per_kwy']
    fleet_co2e_converted_tonnes = fleet_ch4_converted_tonnes * p['co2e_ratio']
    fleet_total_net_co2e        = fleet_co2e_converted_tonnes * p['credit_price_per_tonne_co2e']
    return {
        'ship_fraction_of_year':         ship_fraction_of_year,
        'ship_energy_used_kwy':          ship_energy_used_kwy,
        'ship_energy_cost_per_year':     ship_energy_cost_per_year,
        'ship_ch4_converted_tonnes':     ship_ch4_converted_tonnes,
        'ship_co2e_converted_tonnes':    ship_co2e_converted_tonnes,
        'ship_revenue_ch4':              ship_revenue_ch4,
        'ship_revenue_co2e':             ship_revenue_co2e,
        'ship_net_ch4':                  ship_net_ch4,
        'ship_net_co2e':                 ship_net_co2e,
        'ship_cost_per_tonne_ch4':       ship_cost_per_tonne_ch4,
        'ship_cost_per_tonne_co2e':      ship_cost_per_tonne_co2e,
        'fleet_total_power_mw':          fleet_total_power_mw,
        'fleet_real_power_mw':           fleet_real_power_mw,
        'fleet_ch4_converted_tonnes':    fleet_ch4_converted_tonnes,
        'fleet_co2e_converted_tonnes':   fleet_co2e_converted_tonnes,
        'fleet_total_net_co2e':          fleet_total_net_co2e,
    }


def compute_solar(p):
    solar_available_kw            = p['solar_nameplate_mw'] * 1_000 * p['solar_nameplate_ratio']
    solar_energy_used_kwy         = solar_available_kw              # kWy/year (kW × 1 yr)
    solar_acreage                 = p['solar_nameplate_mw'] * p['solar_land_use_acres_per_mw']
    solar_annual_capex            = (p['solar_nameplate_mw'] * p['solar_cap_cost_per_mw_nameplate']
                                     / p['solar_panel_lifetime_years'])
    solar_annual_cap_cost_per_kwy = solar_annual_capex / solar_energy_used_kwy
    solar_ch4_converted_tonnes    = solar_energy_used_kwy * p['ch4_per_kwy']
    solar_co2e_converted_tonnes   = solar_ch4_converted_tonnes * p['co2e_ratio']
    solar_revenue_ch4             = solar_ch4_converted_tonnes  * p['credit_price_per_tonne_ch4']
    solar_revenue_co2e            = solar_co2e_converted_tonnes * p['credit_price_per_tonne_co2e']
    solar_net_ch4                 = solar_revenue_ch4  - solar_annual_capex
    solar_net_co2e                = solar_revenue_co2e - solar_annual_capex
    solar_cost_per_tonne_ch4      = solar_annual_capex / solar_ch4_converted_tonnes
    solar_cost_per_tonne_co2e     = solar_annual_capex / solar_co2e_converted_tonnes
    target_tonnes                 = p['target_megatonnes'] / megatonnes_per_tonne
    solar_nameplate_for_target_mw = ((target_tonnes / p['ch4_per_kwy'])
                                     / (p['solar_nameplate_ratio'] * 1_000))
    solar_acreage_for_target      = solar_nameplate_for_target_mw * p['solar_land_use_acres_per_mw']
    return {
        'solar_acreage':                    solar_acreage,
        'solar_available_kw':               solar_available_kw,
        'solar_energy_used_kwy':            solar_energy_used_kwy,
        'solar_annual_capex':               solar_annual_capex,
        'solar_annual_cap_cost_per_kwy':    solar_annual_cap_cost_per_kwy,
        'solar_ch4_converted_tonnes':       solar_ch4_converted_tonnes,
        'solar_co2e_converted_tonnes':      solar_co2e_converted_tonnes,
        'solar_revenue_ch4':                solar_revenue_ch4,
        'solar_revenue_co2e':               solar_revenue_co2e,
        'solar_net_ch4':                    solar_net_ch4,
        'solar_net_co2e':                   solar_net_co2e,
        'solar_cost_per_tonne_ch4':         solar_cost_per_tonne_ch4,
        'solar_cost_per_tonne_co2e':        solar_cost_per_tonne_co2e,
        'solar_nameplate_for_target_mw':    solar_nameplate_for_target_mw,
        'solar_acreage_for_target':         solar_acreage_for_target,
    }


def compute_landfill(p):
    landfill_available_kw            = (p['landfill_nameplate_mw'] * 1_000
                                        * p['solar_nameplate_ratio'])
    landfill_energy_used_kwy         = landfill_available_kw
    landfill_acreage                 = p['landfill_nameplate_mw'] * p['solar_land_use_acres_per_mw']
    landfill_annual_capex            = (p['landfill_construction_premium']
                                        * p['landfill_nameplate_mw']
                                        * p['solar_cap_cost_per_mw_nameplate']
                                        / p['solar_panel_lifetime_years'])
    landfill_annual_cap_cost_per_kwy = landfill_annual_capex / landfill_energy_used_kwy
    landfill_concentration_factor    = (1_000 * p['landfill_ch4_concentration_ppm']
                                        / p['ch4_reference_concentration_ppb'])
    landfill_ch4_converted_tonnes    = (landfill_energy_used_kwy * p['ch4_per_kwy']
                                        * landfill_concentration_factor)
    landfill_co2e_converted_tonnes   = landfill_ch4_converted_tonnes * p['co2e_ratio']
    landfill_revenue_ch4             = landfill_ch4_converted_tonnes  * p['credit_price_per_tonne_ch4']
    landfill_revenue_co2e            = landfill_co2e_converted_tonnes * p['credit_price_per_tonne_co2e']
    landfill_net_ch4                 = landfill_revenue_ch4  - landfill_annual_capex
    landfill_net_co2e                = landfill_revenue_co2e - landfill_annual_capex
    landfill_cost_per_tonne_ch4      = landfill_annual_capex / landfill_ch4_converted_tonnes
    landfill_cost_per_tonne_co2e     = landfill_annual_capex / landfill_co2e_converted_tonnes
    landfill_capital_cost            = (p['landfill_construction_premium']
                                        * p['landfill_nameplate_mw']
                                        * p['solar_cap_cost_per_mw_nameplate'])
    return {
        'landfill_acreage':                  landfill_acreage,
        'landfill_available_kw':             landfill_available_kw,
        'landfill_energy_used_kwy':          landfill_energy_used_kwy,
        'landfill_annual_capex':             landfill_annual_capex,
        'landfill_annual_cap_cost_per_kwy':  landfill_annual_cap_cost_per_kwy,
        'landfill_concentration_factor':     landfill_concentration_factor,
        'landfill_ch4_converted_tonnes':     landfill_ch4_converted_tonnes,
        'landfill_co2e_converted_tonnes':    landfill_co2e_converted_tonnes,
        'landfill_revenue_ch4':              landfill_revenue_ch4,
        'landfill_revenue_co2e':             landfill_revenue_co2e,
        'landfill_net_ch4':                  landfill_net_ch4,
        'landfill_net_co2e':                 landfill_net_co2e,
        'landfill_cost_per_tonne_ch4':       landfill_cost_per_tonne_ch4,
        'landfill_cost_per_tonne_co2e':      landfill_cost_per_tonne_co2e,
        'landfill_capital_cost':             landfill_capital_cost,
    }


def compute_troposphere(p):
    wh_to_remove_1ppm_troposphere = p['troposphere_volume_m3'] * p['wh_to_remove_1ppm_per_m3']
    wy_to_remove_1ppm_troposphere = wh_to_remove_1ppm_troposphere / hours_per_year
    nukes_needed                  = wy_to_remove_1ppm_troposphere / p['nuclear_plant_output_wy']
    nukes_with_improvements       = (nukes_needed / p['led_efficiency_multiplier']
                                     / p['engineering_improvement'] / p['years_to_run'])
    total_cost                    = nukes_needed * p['cost_per_micronuke']
    annual_cost                   = total_cost / p['years_to_run']
    solar_wy_required             = wy_to_remove_1ppm_troposphere
    solar_w_per_year              = solar_wy_required / p['years_to_run']
    return {
        'wh_to_remove_1ppm_troposphere':  wh_to_remove_1ppm_troposphere,
        'wy_to_remove_1ppm_troposphere':  wy_to_remove_1ppm_troposphere,
        'nukes_needed':                   nukes_needed,
        'nukes_with_improvements':        nukes_with_improvements,
        'total_cost':                     total_cost,
        'annual_cost':                    annual_cost,
        'solar_wy_required':              solar_wy_required,
        'solar_w_per_year':               solar_w_per_year,
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

    if 'ship_energy_used_kwy' in outputs:
        print('\n--- Ship Ambient (single device) ---')
        print(f"  Energy used:                    {outputs['ship_energy_used_kwy']:.3f} kWy")
        print(f"  Energy cost/year:              {fmt(outputs['ship_energy_cost_per_year'])}")
        print(f"  CH4 converted:                  {outputs['ship_ch4_converted_tonnes']:.4f} t CH4")
        print(f"  CO2e converted:                 {outputs['ship_co2e_converted_tonnes']:.4f} t CO2e")
        print(f"  Revenue (CH4 credits):         {fmt(outputs['ship_revenue_ch4'])}")
        print(f"  Revenue (CO2e credits):        {fmt(outputs['ship_revenue_co2e'])}")
        print(f"  Net $ (CH4 basis):             {fmt(outputs['ship_net_ch4'])}")
        print(f"  Net $ (CO2e basis):            {fmt(outputs['ship_net_co2e'])}")
        print(f"  Cost/tonne CH4:                {fmt(outputs['ship_cost_per_tonne_ch4'])}")
        print(f"  Cost/tonne CO2e:               {fmt(outputs['ship_cost_per_tonne_co2e'])}")
        print(f"  Fleet CH4/year:                 {outputs['fleet_ch4_converted_tonnes']:,.1f} t")
        print(f"  Fleet CO2e/year:                {outputs['fleet_co2e_converted_tonnes']:,.1f} t")
        print(f"  Fleet CO2e revenue:            {fmt(outputs['fleet_total_net_co2e'])}")

    if 'solar_energy_used_kwy' in outputs:
        print('\n--- Solar Field Ambient ---')
        print(f"  Acreage:                        {outputs['solar_acreage']:,.0f} acres")
        print(f"  Energy used:                    {outputs['solar_energy_used_kwy']:,.0f} kWy")
        print(f"  Annual capex:                  {fmt(outputs['solar_annual_capex'])}")
        print(f"  CH4 converted:                  {outputs['solar_ch4_converted_tonnes']:,.1f} t CH4")
        print(f"  CO2e converted:                 {outputs['solar_co2e_converted_tonnes']:,.1f} t CO2e")
        print(f"  Revenue (CH4):                 {fmt(outputs['solar_revenue_ch4'])}")
        print(f"  Revenue (CO2e):                {fmt(outputs['solar_revenue_co2e'])}")
        print(f"  Net $ (CH4):                   {fmt(outputs['solar_net_ch4'])}")
        print(f"  Net $ (CO2e):                  {fmt(outputs['solar_net_co2e'])}")
        print(f"  Cost/tonne CH4:                {fmt(outputs['solar_cost_per_tonne_ch4'])}")
        print(f"  Cost/tonne CO2e:               {fmt(outputs['solar_cost_per_tonne_co2e'])}")
        print(f"  MW for {params.get('target_megatonnes',100)} Mt target:          "
              f"{outputs['solar_nameplate_for_target_mw']:,.0f} MW")

    if 'landfill_energy_used_kwy' in outputs:
        print('\n--- Landfill Solar Field ---')
        print(f"  Concentration factor:           {outputs['landfill_concentration_factor']:,.0f}x")
        print(f"  Annual capex:                  {fmt(outputs['landfill_annual_capex'])}")
        print(f"  CH4 converted:                  {outputs['landfill_ch4_converted_tonnes']:,.1f} t CH4")
        print(f"  CO2e converted:                 {outputs['landfill_co2e_converted_tonnes']:,.1f} t CO2e")
        print(f"  Revenue (CH4):                 {fmt(outputs['landfill_revenue_ch4'])}")
        print(f"  Revenue (CO2e):                {fmt(outputs['landfill_revenue_co2e'])}")
        print(f"  Net $ (CH4):                   {fmt(outputs['landfill_net_ch4'])}")
        print(f"  Net $ (CO2e):                  {fmt(outputs['landfill_net_co2e'])}")
        print(f"  Total capital cost:            {fmt(outputs['landfill_capital_cost'])}")

    if 'wy_to_remove_1ppm_troposphere' in outputs:
        print('\n--- Global / Troposphere ---')
        print(f"  Energy to remove 1 ppm:         {outputs['wy_to_remove_1ppm_troposphere']:.3e} Wy")
        print(f"  Nuclear plants required:        {outputs['nukes_needed']:.3e}")
        print(f"  With LED + engineering:         {outputs['nukes_with_improvements']:.3e}")
        print(f"  Total cost:                    {fmt(outputs['total_cost'])}")
        print(f"  Annual cost:                   {fmt(outputs['annual_cost'])}")
        print(f"  Solar power needed:             {outputs['solar_w_per_year']:.3e} W")

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
