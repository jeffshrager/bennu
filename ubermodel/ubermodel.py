"""
Cost of Methane Destruction Model
==================================
Translated from: Cost_of_methane_destruction.xlsx

Three independent dimensions select the scenario:

  --setting  deployment context   ship | field | landfill | troposphere | all
  --power    energy source        solar | nuclear | ship_engine | grid
  --device   CH4 destruction tech fluorescent | led

Parameter naming convention:
  I_  primary inputs      physical/experimental values; main user-facing knobs
  B_  background values   scenario settings; stable defaults rarely changed
  P_  partial results     intermediate computed values; never set by the user
  O_  primary outputs     final results reported in the terminal and TSV

Any I_ or B_ parameter may be overridden from the command line, including as a
range sweep [low,high,step]:
  --I_ch4_per_kwy 4.5
  --B_solar_nameplate_mw '[50,200,50]'    (quote ranges to prevent shell glob)

--setting all runs the four canonical combinations (original scenarios):
  ship + ship_engine + fluorescent
  field + solar      + fluorescent
  landfill + solar   + fluorescent
  troposphere + nuclear + fluorescent

Supported setting+power pairs:
  ship+ship_engine, field+solar, landfill+solar,
  troposphere+nuclear, troposphere+solar
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
J    = 1;  W   = 1;   kW  = 1_000 * W;  MW  = 1_000 * kW
Wh   = 3_600 * J;     kWh = kW * Wh;    MWh = MW * Wh
ppm  = 1.0;            ppb = ppm / 1_000
hours_per_year       = 365.25 * 24
kWy  = kW * hours_per_year * Wh          # Kilowatt-year in Joules
MWy  = MW * hours_per_year * Wh
megatonnes_per_tonne = 1e-6

# =============================================================================
# I_  PRIMARY INPUTS  (physical / experimental — scenario-independent)
# =============================================================================
PRIMARY_INPUTS = {
    'I_ch4_per_kwy':                     3.0,    # t CH4 destroyed per kWy at reference conc.
    'I_co2e_ratio':                      28,     # 100-yr GWP of CH4 vs CO2
    'I_ch4_reference_concentration_ppb': 2_000,  # ppb – conc. at which ratio was measured
    'I_credit_price_per_tonne_ch4':      1_200,  # $/t CH4  (EPA Methane Fee 2025)
    'I_credit_price_per_tonne_co2e':     100,    # $/t CO2e (voluntary market target)
}

# =============================================================================
# B_  DEPLOYMENT SETTINGS  (where the device is deployed)
# =============================================================================
DEPLOYMENT_SETTINGS = {

    # Ocean-going vessels; CH4 at ambient concentration
    'ship': {
        'B_ship_powerplant_mw':       60,       # MW  – typical ship propulsion power
        'B_ship_device_power_kw':     100,      # kW  – power allocated to CH4 device
        'B_ship_days_per_year':       250,      # days at sea per year
        'B_global_ship_fleet':        80_000,   # total ocean-going vessels (reference)
        'B_plausible_equipped_fleet': 10_000,   # vessels plausibly fitted with devices
        'B_avg_power_per_ship_mw':    1,        # MW device power per equipped ship
    },

    # Open ground (solar farm, tundra, etc.); ambient CH4 concentration
    'field': {
        'B_target_megatonnes': 100,             # Mt CH4/yr climate-policy target
    },

    # Landfill surface; elevated CH4 concentration boosts conversion
    'landfill': {
        'B_landfill_nameplate_mw':          100,        # MW – solar field nameplate
        'B_landfill_construction_premium':  4,          # capex multiplier vs standard solar
        'B_landfill_ch4_concentration_ppm': 500,        # ppm – EPA remediation threshold
    },

    # Global-scale inverse analysis: how much capacity needed to move 1 ppm?
    'troposphere': {
        'B_troposphere_volume_m3':     1e18,    # m³ – approximate troposphere volume
        'B_wh_to_remove_1ppm_per_m3':  50,     # Wh to remove 1 ppm CH4 from 1 m³ of air
        'B_years_to_run':               10,    # campaign time horizon (years)
        'B_engineering_improvement':    10,    # further device improvement factor (R&D)
        'B_target_megatonnes':          100,   # Mt CH4/yr climate-policy target
    },
}

# =============================================================================
# B_  POWER SETTINGS  (how the device is powered)
# =============================================================================
POWER_SETTINGS = {

    # Photovoltaic solar field
    'solar': {
        'B_solar_nameplate_mw':              100,        # MW – field nameplate capacity
        'B_solar_cap_cost_per_mw_nameplate': 1_000_000,  # $/MW installed (~$1/W, USA)
        'B_solar_land_use_acres_per_mw':     4,          # acres per MW nameplate
        'B_solar_nameplate_ratio':           0.40,       # capacity factor (output/nameplate)
        'B_solar_panel_lifetime_years':      25,         # assumed panel service life
    },

    # Small modular / micro nuclear reactors
    'nuclear': {
        'B_nuclear_plant_output_wy': 30_000_000,  # Wy – annual output of one nuclear plant
        'B_cost_per_micronuke':      20_000_000,  # $ – capital cost of one micro-reactor
    },

    # Ship's own propulsion power
    'ship_engine': {
        'B_energy_cost_ship_per_kwh': 0.25,       # $/kWh – shipboard electricity
    },

    # USA wholesale grid electricity
    'grid': {
        'B_energy_cost_usa_per_mwh': 30.0,        # $/MWh – USA 2023 wholesale average
    },
}

# =============================================================================
# B_  DEVICE SETTINGS  (the CH4 photo-catalytic destruction technology)
# =============================================================================
DEVICE_SETTINGS = {
    # Baseline fluorescent-lamp device (the original ch4_per_kwy measurement)
    'fluorescent': {
        'B_device_efficiency_multiplier': 1.0,
    },
    # LED-based device; substantially more efficient than fluorescent
    'led': {
        'B_device_efficiency_multiplier': 1_000,
    },
}

# =============================================================================
# SCENARIO METADATA
# =============================================================================

# Canonical combinations that reproduce the four original scenarios
CANONICAL_COMBOS = [
    ('ship',        'ship_engine', 'fluorescent'),
    ('field',       'solar',       'fluorescent'),
    ('landfill',    'solar',       'fluorescent'),
    ('troposphere', 'nuclear',     'fluorescent'),
]

# Default power source when --power is omitted for a named setting
DEFAULT_POWER = {
    'ship':        'ship_engine',
    'field':       'solar',
    'landfill':    'solar',
    'troposphere': 'nuclear',
}

# Pairs with defined compute logic; others are rejected with a clear error
SUPPORTED_COMBOS = {
    ('ship',        'ship_engine'),
    ('field',       'solar'),
    ('landfill',    'solar'),
    ('troposphere', 'nuclear'),
    ('troposphere', 'solar'),
}

# =============================================================================
# COMPUTE
# =============================================================================

def build_params(setting_name, power_name, device_name, overrides=None):
    """Merge the four parameter dicts for this combination, then apply overrides."""
    p = {}
    p.update(PRIMARY_INPUTS)
    p.update(DEPLOYMENT_SETTINGS[setting_name])
    p.update(POWER_SETTINGS[power_name])
    p.update(DEVICE_SETTINGS[device_name])
    if overrides:
        p.update(overrides)
    return p


def compute(setting_name, power_name, device_name, p):
    """
    Run the model for one (setting, power, device) combination.
    Returns a dict of P_ (partial/intermediate) and O_ (output) values.
    """
    if (setting_name, power_name) not in SUPPORTED_COMBOS:
        raise ValueError(
            f"Unsupported combination: setting={setting_name!r}, power={power_name!r}. "
            "Supported setting+power pairs: "
            + ', '.join(f'{s}+{pw}' for s, pw in sorted(SUPPORTED_COMBOS))
        )

    out = {}

    # ── Device (applies to every combination) ────────────────────────────────
    device_mult           = p['B_device_efficiency_multiplier']
    effective_ch4_per_kwy = p['I_ch4_per_kwy'] * device_mult
    out['P_device_efficiency_multiplier'] = device_mult
    out['P_effective_ch4_per_kwy']        = effective_ch4_per_kwy

    # ── Troposphere: inverse model ────────────────────────────────────────────
    if setting_name == 'troposphere':
        wh_raw  = p['B_troposphere_volume_m3'] * p['B_wh_to_remove_1ppm_per_m3']
        wy_raw  = wh_raw / hours_per_year
        # Energy after device efficiency and engineering improvement
        wy_need = wy_raw / device_mult / p['B_engineering_improvement']
        out['P_wh_to_remove_1ppm_raw'] = wh_raw
        out['P_wy_to_remove_1ppm_raw'] = wy_raw
        out['P_wy_needed']             = wy_need

        if power_name == 'nuclear':
            # Raw: plants needed to do the whole job in 1 year, no improvements
            nukes_raw  = wy_raw / p['B_nuclear_plant_output_wy']
            # With device + engineering, spread over campaign years
            nukes_need = wy_need / (p['B_nuclear_plant_output_wy'] * p['B_years_to_run'])
            tot_cost   = nukes_need * p['B_cost_per_micronuke']
            out['O_nukes_raw']    = nukes_raw
            out['O_nukes_needed'] = nukes_need
            out['O_total_cost']   = tot_cost
            out['O_annual_cost']  = tot_cost / p['B_years_to_run']

        elif power_name == 'solar':
            # Average watts needed (sustained over campaign), before/after improvements
            solar_w_raw  = wy_raw  / p['B_years_to_run']
            solar_w_need = wy_need / p['B_years_to_run']
            solar_mw     = solar_w_need / (p['B_solar_nameplate_ratio'] * 1e6)
            tot_capex    = solar_mw * p['B_solar_cap_cost_per_mw_nameplate']
            out['O_solar_w_raw']               = solar_w_raw
            out['O_solar_w_needed']            = solar_w_need
            out['O_solar_mw_nameplate_needed'] = solar_mw
            out['O_solar_acreage_needed']      = solar_mw * p['B_solar_land_use_acres_per_mw']
            out['O_total_cost']                = tot_capex
            out['O_annual_cost']               = tot_capex / p['B_solar_panel_lifetime_years']

        return out

    # ── Forward models: ship, field, landfill ─────────────────────────────────

    # Concentration factor relative to device reference
    if setting_name == 'landfill':
        conc = (1_000 * p['B_landfill_ch4_concentration_ppm']
                / p['I_ch4_reference_concentration_ppb'])
    else:
        conc = 1.0          # ambient = reference concentration
    out['P_concentration_factor'] = conc

    # Energy available and annual cost, determined by power source
    if power_name == 'ship_engine':
        frac         = p['B_ship_days_per_year'] / 365
        cost_per_kwy = p['B_energy_cost_ship_per_kwh'] * hours_per_year
        energy_kwy   = p['B_ship_device_power_kw'] * frac
        annual_cost  = energy_kwy * cost_per_kwy
        out['P_ship_fraction_of_year'] = frac
        out['P_energy_kwy']            = energy_kwy
        out['P_annual_cost']           = annual_cost

    elif power_name == 'solar':
        # Landfill uses its own nameplate and adds a construction premium
        nameplate_mw = (p['B_landfill_nameplate_mw'] if setting_name == 'landfill'
                        else p['B_solar_nameplate_mw'])
        premium      = (p['B_landfill_construction_premium'] if setting_name == 'landfill'
                        else 1.0)
        energy_kwy   = nameplate_mw * 1_000 * p['B_solar_nameplate_ratio']
        annual_capex = (premium * nameplate_mw * p['B_solar_cap_cost_per_mw_nameplate']
                        / p['B_solar_panel_lifetime_years'])
        out['P_nameplate_mw']               = nameplate_mw
        out['P_solar_construction_premium'] = premium
        out['P_energy_kwy']                 = energy_kwy
        out['P_annual_cost']                = annual_capex
        out['O_acreage']     = nameplate_mw * p['B_solar_land_use_acres_per_mw']
        out['O_capital_cost']= premium * nameplate_mw * p['B_solar_cap_cost_per_mw_nameplate']

    # CH4 conversion and core economics
    ch4      = energy_kwy * effective_ch4_per_kwy * conc
    co2e     = ch4 * p['I_co2e_ratio']
    cost     = out['P_annual_cost']
    rev_ch4  = ch4  * p['I_credit_price_per_tonne_ch4']
    rev_co2e = co2e * p['I_credit_price_per_tonne_co2e']
    out['O_ch4_converted_tonnes']  = ch4
    out['O_co2e_converted_tonnes'] = co2e
    out['O_revenue_ch4']           = rev_ch4
    out['O_revenue_co2e']          = rev_co2e
    out['O_net_ch4']               = rev_ch4  - cost
    out['O_net_co2e']              = rev_co2e - cost
    out['O_cost_per_tonne_ch4']    = cost / ch4
    out['O_cost_per_tonne_co2e']   = cost / co2e

    # Ship: fleet-scale outputs
    if setting_name == 'ship':
        frac          = out['P_ship_fraction_of_year']
        fleet_mw      = p['B_plausible_equipped_fleet'] * p['B_avg_power_per_ship_mw']
        fleet_real_mw = fleet_mw * frac
        fleet_ch4     = fleet_real_mw * 1_000 * effective_ch4_per_kwy
        fleet_co2e    = fleet_ch4 * p['I_co2e_ratio']
        out['P_fleet_total_power_mw']        = fleet_mw
        out['P_fleet_real_power_mw']         = fleet_real_mw
        out['O_fleet_ch4_converted_tonnes']  = fleet_ch4
        out['O_fleet_co2e_converted_tonnes'] = fleet_co2e
        out['O_fleet_total_net_co2e']        = fleet_co2e * p['I_credit_price_per_tonne_co2e']

    # Field + solar: scale-up to policy target
    if setting_name == 'field':
        target_t = p['B_target_megatonnes'] / megatonnes_per_tonne
        mw_for_t = (target_t / effective_ch4_per_kwy) / (p['B_solar_nameplate_ratio'] * 1_000)
        out['O_solar_mw_for_target']    = mw_for_t
        out['O_solar_acres_for_target'] = mw_for_t * p['B_solar_land_use_acres_per_mw']

    return out

# =============================================================================
# TERMINAL OUTPUT
# =============================================================================

def fmt(v, prefix='$', dec=2):
    return f'{prefix}{v:,.{dec}f}' if prefix else f'{v:,.{dec}f}'


def print_results(setting_name, power_name, device_name, params, out):
    print('=' * 65)
    print('METHANE DESTRUCTION COST MODEL')
    print(f'  Setting: {setting_name}   Power: {power_name}   Device: {device_name}')
    mult = out.get('P_device_efficiency_multiplier', 1.0)
    if mult != 1.0:
        print(f'  Device efficiency: {mult:,.0f}x  '
              f'=> {out["P_effective_ch4_per_kwy"]:.1f} t CH4/kWy effective')
    print('=' * 65)

    if setting_name == 'troposphere':
        print(f'\n  Energy to remove 1 ppm (raw):   {out["P_wy_to_remove_1ppm_raw"]:.3e} Wy')
        print(f'  After device + engineering:     {out["P_wy_needed"]:.3e} Wy')
        if 'O_nukes_needed' in out:
            print(f'  Nuclear plants (raw, 1 yr):     {out["O_nukes_raw"]:.3e}')
            print(f'  Nuclear plants (with improvements, {params["B_years_to_run"]} yr campaign): '
                  f'{out["O_nukes_needed"]:.3e}')
        if 'O_solar_mw_nameplate_needed' in out:
            print(f'  Solar avg power (raw):          {out["O_solar_w_raw"]:.3e} W')
            print(f'  Solar avg power (with improv.): {out["O_solar_w_needed"]:.3e} W')
            print(f'  Solar nameplate needed:         {out["O_solar_mw_nameplate_needed"]:,.0f} MW')
            print(f'  Solar acreage needed:           {out["O_solar_acreage_needed"]:,.0f} acres')
        print(f'  Total cost:                    {fmt(out["O_total_cost"])}')
        print(f'  Annual cost:                   {fmt(out["O_annual_cost"])}')

    elif setting_name == 'ship':
        print(f'\n  Energy used:                    {out["P_energy_kwy"]:.3f} kWy')
        print(f'  Energy cost/year:              {fmt(out["P_annual_cost"])}')
        print(f'  CH4 converted:                  {out["O_ch4_converted_tonnes"]:.4f} t')
        print(f'  CO2e converted:                 {out["O_co2e_converted_tonnes"]:.4f} t')
        print(f'  Revenue (CH4 credits):         {fmt(out["O_revenue_ch4"])}')
        print(f'  Revenue (CO2e credits):        {fmt(out["O_revenue_co2e"])}')
        print(f'  Net $ (CH4):                   {fmt(out["O_net_ch4"])}')
        print(f'  Net $ (CO2e):                  {fmt(out["O_net_co2e"])}')
        print(f'  Cost/tonne CH4:                {fmt(out["O_cost_per_tonne_ch4"])}')
        print(f'  Cost/tonne CO2e:               {fmt(out["O_cost_per_tonne_co2e"])}')
        print(f'  Fleet CH4/year:                 {out["O_fleet_ch4_converted_tonnes"]:,.1f} t')
        print(f'  Fleet CO2e/year:                {out["O_fleet_co2e_converted_tonnes"]:,.1f} t')
        print(f'  Fleet CO2e revenue:            {fmt(out["O_fleet_total_net_co2e"])}')

    elif setting_name == 'field':
        print(f'\n  Acreage:                        {out["O_acreage"]:,.0f} acres')
        print(f'  Energy used:                    {out["P_energy_kwy"]:,.0f} kWy')
        print(f'  Annual capex:                  {fmt(out["P_annual_cost"])}')
        print(f'  CH4 converted:                  {out["O_ch4_converted_tonnes"]:,.1f} t')
        print(f'  CO2e converted:                 {out["O_co2e_converted_tonnes"]:,.1f} t')
        print(f'  Revenue (CH4):                 {fmt(out["O_revenue_ch4"])}')
        print(f'  Revenue (CO2e):                {fmt(out["O_revenue_co2e"])}')
        print(f'  Net $ (CH4):                   {fmt(out["O_net_ch4"])}')
        print(f'  Net $ (CO2e):                  {fmt(out["O_net_co2e"])}')
        print(f'  Cost/tonne CH4:                {fmt(out["O_cost_per_tonne_ch4"])}')
        print(f'  Cost/tonne CO2e:               {fmt(out["O_cost_per_tonne_co2e"])}')
        print(f'  MW for {params.get("B_target_megatonnes",100)} Mt target:           '
              f'{out["O_solar_mw_for_target"]:,.0f} MW')

    elif setting_name == 'landfill':
        print(f'\n  Concentration factor:           {out["P_concentration_factor"]:,.0f}x')
        print(f'  Acreage:                        {out["O_acreage"]:,.0f} acres')
        print(f'  Annual capex:                  {fmt(out["P_annual_cost"])}')
        print(f'  CH4 converted:                  {out["O_ch4_converted_tonnes"]:,.1f} t')
        print(f'  CO2e converted:                 {out["O_co2e_converted_tonnes"]:,.1f} t')
        print(f'  Revenue (CH4):                 {fmt(out["O_revenue_ch4"])}')
        print(f'  Revenue (CO2e):                {fmt(out["O_revenue_co2e"])}')
        print(f'  Net $ (CH4):                   {fmt(out["O_net_ch4"])}')
        print(f'  Net $ (CO2e):                  {fmt(out["O_net_co2e"])}')
        print(f'  Total capital cost:            {fmt(out["O_capital_cost"])}')

    print('=' * 65)

# =============================================================================
# CLI + TSV OUTPUT
# =============================================================================

def parse_range_arg(s):
    """'nnn' -> [float]  or  '[low,high,step]' -> [float, ...]"""
    s = s.strip()
    if s.startswith('[') and s.endswith(']'):
        parts = s[1:-1].split(',')
        if len(parts) != 3:
            raise ValueError(f"Range must be [low,high,step], got: {s}")
        low, high, step = float(parts[0]), float(parts[1]), float(parts[2])
        vals, v = [], low
        while v <= high + step * 1e-9:
            vals.append(round(v, 12))
            v += step
        if not vals:
            raise ValueError(f"Empty range: {s}")
        return vals
    return [float(s)]


def main():
    all_known_params = set(PRIMARY_INPUTS)
    for d in (list(DEPLOYMENT_SETTINGS.values()) + list(POWER_SETTINGS.values())
              + list(DEVICE_SETTINGS.values())):
        all_known_params.update(d)

    parser = argparse.ArgumentParser(
        description='Methane Destruction Cost Model',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument('--setting', default='all',
                        choices=['all'] + list(DEPLOYMENT_SETTINGS.keys()),
                        help='Deployment context (default: all)')
    parser.add_argument('--power', default=None,
                        choices=list(POWER_SETTINGS.keys()),
                        help='Power source (default: canonical per setting)')
    parser.add_argument('--device', default='fluorescent',
                        choices=list(DEVICE_SETTINGS.keys()),
                        help='Device technology (default: fluorescent)')
    known, remaining = parser.parse_known_args()

    # ── Determine (setting, power, device) combinations to run ───────────────
    if known.setting == 'all':
        # Use canonical power defaults; apply --device to all; honour --power override
        raw_combos = [(s, known.power or pw, known.device)
                      for s, pw, _ in CANONICAL_COMBOS]
    else:
        power = known.power or DEFAULT_POWER[known.setting]
        raw_combos = [(known.setting, power, known.device)]

    # Filter out unsupported setting+power pairs with a warning
    combos = []
    for s, pw, dv in raw_combos:
        if (s, pw) not in SUPPORTED_COMBOS:
            print(f"Warning: skipping unsupported combination "
                  f"setting={s!r}, power={pw!r}", file=sys.stderr)
        else:
            combos.append((s, pw, dv))
    if not combos:
        print("Error: no valid combinations to run.", file=sys.stderr)
        sys.exit(1)

    # ── Parse remaining args as --param_name value_or_range ──────────────────
    overrides = {}
    i = 0
    while i < len(remaining):
        tok = remaining[i]
        if not tok.startswith('--'):
            parser.error(f"Unexpected token: {tok!r}")
        pname = tok[2:]
        if i + 1 >= len(remaining):
            parser.error(f"--{pname} requires a value")
        try:
            overrides[pname] = parse_range_arg(remaining[i + 1])
        except ValueError as e:
            parser.error(str(e))
        i += 2

    for pname in overrides:
        if pname not in all_known_params:
            print(f"Warning: '{pname}' is not a recognised parameter name",
                  file=sys.stderr)

    # ── Cartesian product of range overrides ─────────────────────────────────
    if overrides:
        sweep_names  = list(overrides.keys())
        sweep_combos = list(itertools.product(*[overrides[n] for n in sweep_names]))
    else:
        sweep_names, sweep_combos = [], [()]

    # ── Run every (setting, power, device) × parameter combination ───────────
    results = []   # (setting, power, device, params, outputs)
    for s, pw, dv in combos:
        for sweep_vals in sweep_combos:
            p   = build_params(s, pw, dv, dict(zip(sweep_names, sweep_vals)))
            out = compute(s, pw, dv, p)
            results.append((s, pw, dv, p, out))

    # ── Print to terminal ─────────────────────────────────────────────────────
    for s, pw, dv, p, out in results:
        print_results(s, pw, dv, p, out)

    # ── Write timestamped TSV ─────────────────────────────────────────────────
    os.makedirs('results', exist_ok=True)
    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
    label    = known.setting
    tsv_path = os.path.join('results', f'results_{label}_{ts}.tsv')

    # Column order: identity | I_ | B_ | P_ | O_  (union across all rows)
    all_keys = set()
    for _, _, _, p, out in results:
        all_keys.update(p); all_keys.update(out)
    i_cols = sorted(k for k in all_keys if k.startswith('I_'))
    b_cols = sorted(k for k in all_keys if k.startswith('B_'))
    p_cols = sorted(k for k in all_keys if k.startswith('P_'))
    o_cols = sorted(k for k in all_keys if k.startswith('O_'))
    fieldnames = ['setting', 'power', 'device'] + i_cols + b_cols + p_cols + o_cols

    with open(tsv_path, 'w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter='\t')
        writer.writeheader()
        for s, pw, dv, p, out in results:
            row = {'setting': s, 'power': pw, 'device': dv}
            row.update(p); row.update(out)
            writer.writerow({k: row.get(k, '') for k in fieldnames})

    n = len(results)
    print(f"\nResults written to: {tsv_path}  ({n} row{'s' if n != 1 else ''})")


if __name__ == '__main__':
    main()
