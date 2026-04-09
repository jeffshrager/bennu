"""
Cost of Methane Destruction Model
==================================
Translated from: Cost_of_methane_destruction.xlsx
Sheets modelled: Calculations Master, Summary Master

This script estimates the cost and carbon-credit revenue of photo-catalytic
CH4 destruction across three deployment scenarios:
  1. Ship Ambient       – devices mounted on ocean-going vessels
  2. Solar Field Ambient – devices co-located with a ground-mounted solar farm
  3. Landfill Solar Field – devices under solar panels sited on a landfill

All monetary values are in USD.  Mass is in metric tonnes.
Energy is expressed in SI units (Joules) plus practical units (kWh, kWy).
"""

# =============================================================================
# SECTION 1 – UNIT DEFINITIONS
# All values relative to the base SI unit listed in the comment.
# =============================================================================

J    = 1                     # Joule  (base unit of energy)
W    = 1                     # Watt   = 1 J/s  (base unit of power)
kW   = 1_000  * W            # Kilowatt
MW   = 1_000  * kW           # Megawatt
Wh   = 3_600  * J            # Watt-hour   (energy delivered at 1 W for 1 hour)
kWh  = kW     * Wh           # Kilowatt-hour
MWh  = MW     * Wh           # Megawatt-hour

ppm  = 1.0                   # Parts per million (mixing-ratio unit)
ppb  = ppm / 1_000           # Parts per billion

hours_per_year        = 365.25 * 24          # Hours in a calendar year (~8 766 h)
sunlight_hours_per_year = hours_per_year / 2 # Approximate solar irradiance hours/year

kWy  = kW * hours_per_year * Wh    # Kilowatt-year in Joules
MWy  = MW * hours_per_year * Wh    # Megawatt-year in Joules

tonnes_per_gram        = 1e-6      # Conversion: grams → metric tonnes
megatonnes_per_tonne   = 1e-6      # Conversion: metric tonnes → megatonnes
target_megatonnes      = 100       # Climate policy target: remove 100 megatonnes CH4/year
target_tonnes          = target_megatonnes / megatonnes_per_tonne  # = 1e8 tonnes CH4/year

# =============================================================================
# SECTION 2 – CONVERSION RATIO  (key physical input)
# How much CH4 can be photo-catalytically converted per unit of electrical energy,
# measured at the reference concentration below.
# =============================================================================

ch4_reference_concentration_ppb = 2_000   # ppb – concentration at which the ratio was measured

# Core conversion ratio: 1 kWy of device energy converts this many tonnes of CH4
# (experimentally derived; treated as linear with concentration in range 2–50,000 ppm)
ch4_per_kwy = 3.0             # tonnes CH4 destroyed per kWy

co2e_ratio   = 28             # Global-warming potential of CH4 vs CO2 (100-yr GWP)
                              # Used to express CH4 removal as CO2-equivalent tonnes

# Derived conversion ratios
ch4_per_mwy  = ch4_per_kwy * 1_000          # tonnes CH4 per MWy  (1 MWy = 1000 kWy)
co2e_per_kwy = ch4_per_kwy * co2e_ratio     # tonnes CO2e per kWy
co2e_per_mwy = co2e_per_kwy * 1_000         # tonnes CO2e per MWy

# Energy intensity (how many Joules to destroy one tonne of CH4 / CO2e)
j_per_tonne_ch4  = kWy / ch4_per_kwy        # Joules required to destroy 1 tonne CH4
j_per_tonne_co2e = j_per_tonne_ch4 / co2e_ratio  # Joules required to displace 1 tonne CO2e

# =============================================================================
# SECTION 3 – COST OF ENERGY
# Two energy supply contexts are modelled.
# =============================================================================

# -- USA grid electricity (wholesale) --
energy_cost_usa_per_mwh = 30.0   # $/MWh  (average USA 2023 wholesale price)
# Convert to $/kWy (multiply by hours/year, divide by 1000 to go MWh→kWh)
energy_cost_usa_per_kwy = (energy_cost_usa_per_mwh / 1_000) * hours_per_year

# -- Shipboard electricity --
energy_cost_ship_per_kwh = 0.25  # $/kWh  (hypothetical cost; Stylianos 2024 estimate –
                                 # noted as "probably never to be charged")
energy_cost_ship_per_kwy = energy_cost_ship_per_kwh * hours_per_year  # $/kWy

# =============================================================================
# SECTION 4 – CARBON CREDIT PRICES
# Revenue that can be earned by certifiably destroying CH4 / CO2e.
# =============================================================================

credit_price_per_tonne_ch4  = 1_200  # $/tonne CH4   (EPA Methane Fee 2025;
                                     # rising to $1 500/t in 2026 – US ton;
                                     # note: currently only applies to the
                                     # largest fossil-fuel emitters)

credit_price_per_tonne_co2e = 100    # $/tonne CO2e  ("ideal target"; actual
                                     # permanent-removal market closer to $250)

# =============================================================================
# SECTION 5 – SOLAR FIELD PARAMETERS  (capital & land)
# =============================================================================

solar_cap_cost_per_mw_nameplate = 1_000_000  # $/MW nameplate  (~$1/W installed, USA)
solar_land_use_acres_per_mw     = 4          # acres per MW nameplate capacity
solar_nameplate_ratio           = 0.40       # actual average output / nameplate capacity
solar_panel_lifetime_years      = 25         # assumed panel service life in years

# Landfill-sited solar carries a construction premium over standard solar
landfill_construction_premium   = 4          # multiplier on standard solar capex
                                             # (EPA requires landfill remediation above
                                             # 500 ppm CH4; construction is harder there)

landfill_ch4_concentration_ppm  = 500        # ppm – EPA remediation threshold;
                                             # used as the input concentration for
                                             # landfill device performance

# =============================================================================
# SECTION 6 – SHIP AMBIENT MODEL
# Devices mounted on ocean-going vessels destroying ambient-concentration CH4.
# =============================================================================

ship_powerplant_mw          = 60     # MW  – typical ship propulsion power
ship_device_power_kw        = 100    # kW  – power allocated to CH4 destruction device(s)
ship_fraction_of_ship_power = ship_device_power_kw / (ship_powerplant_mw * 1_000)
                                     # fraction of the ship's power used by the device

ship_days_per_year          = 250    # days at sea per year  (14-day round trips;
                                     # 1 day idle in port each side, no emission
                                     # 1 day before/after port)
ship_fraction_of_year       = ship_days_per_year / 365  # fraction of year actually operating

# Annual energy budget for the ship device
ship_energy_used_kwy        = ship_device_power_kw * ship_fraction_of_year
                              # kWy of device energy actually consumed (ship days only)

ship_energy_cost_per_year   = ship_energy_used_kwy * energy_cost_ship_per_kwy
                              # $ – annual electricity cost at shipboard rate

# Annual CH4 / CO2e removal
ship_ch4_converted_tonnes   = ship_energy_used_kwy * ch4_per_kwy
                              # tonnes CH4 destroyed per year (one device / ship)
ship_co2e_converted_tonnes  = ship_ch4_converted_tonnes * co2e_ratio
                              # equivalent tonnes CO2e

# Carbon credit revenue
ship_revenue_ch4            = ship_ch4_converted_tonnes  * credit_price_per_tonne_ch4
ship_revenue_co2e           = ship_co2e_converted_tonnes * credit_price_per_tonne_co2e

# Net economics (revenue minus energy cost)
ship_net_ch4                = ship_revenue_ch4  - ship_energy_cost_per_year
ship_net_co2e               = ship_revenue_co2e - ship_energy_cost_per_year

# Cost per unit of CH4 / CO2e removed (sanity-check metrics)
ship_cost_per_tonne_ch4     = ship_energy_cost_per_year / ship_ch4_converted_tonnes
ship_cost_per_tonne_co2e    = ship_energy_cost_per_year / ship_co2e_converted_tonnes

# -- Fleet scaling --
global_ship_fleet           = 80_000   # total ocean-going vessels (approximate)
plausible_equipped_fleet    = 1   # vessels plausibly fitted with devices (WAG)
avg_power_per_ship_mw       = 1        # MW of device power per ship (WAG)

fleet_total_power_mw        = plausible_equipped_fleet * avg_power_per_ship_mw
fleet_real_power_mw         = fleet_total_power_mw * ship_fraction_of_year
                              # MW – effective continuous power after accounting for ship days

fleet_ch4_converted_tonnes  = fleet_real_power_mw * 1_000 * ch4_per_kwy
                              # tonnes CH4/year across the plausible fleet
fleet_co2e_converted_tonnes = fleet_ch4_converted_tonnes * co2e_ratio
fleet_total_net_co2e        = fleet_co2e_converted_tonnes * credit_price_per_tonne_co2e
                              # $ – total annual carbon-credit revenue for the fleet

# =============================================================================
# SECTION 7 – SOLAR FIELD AMBIENT MODEL
# Dedicated ground-mount solar farm powering CH4 destruction at ambient concentration.
# =============================================================================

solar_nameplate_mw          = 100     # MW – example solar field nameplate capacity

solar_acreage               = solar_nameplate_mw * solar_land_use_acres_per_mw
                              # acres of land required

solar_available_kw          = solar_nameplate_mw * 1_000 * solar_nameplate_ratio
                              # kW of average usable output (nameplate × capacity factor)

solar_energy_used_kwy       = solar_available_kw  # one year of operation
                              # kWy available from the field (capacity × 1 year)

# Annualised capital cost of the solar field
solar_annual_cap_cost       = ((solar_nameplate_mw * solar_cap_cost_per_mw_nameplate)
                               / solar_panel_lifetime_years) / solar_energy_used_kwy
                              # $/kWy – capital cost amortised over panel lifetime

# Annual CH4 / CO2e removal
solar_ch4_converted_tonnes  = solar_energy_used_kwy * ch4_per_kwy
solar_co2e_converted_tonnes = solar_ch4_converted_tonnes * co2e_ratio

# Carbon credit revenue
solar_revenue_ch4           = solar_ch4_converted_tonnes  * credit_price_per_tonne_ch4
solar_revenue_co2e          = solar_co2e_converted_tonnes * credit_price_per_tonne_co2e

# Net economics
solar_net_ch4               = solar_revenue_ch4  - ship_energy_cost_per_year
solar_net_co2e              = solar_revenue_co2e - ship_energy_cost_per_year

solar_cost_per_tonne_ch4    = ship_energy_cost_per_year / solar_ch4_converted_tonnes
solar_cost_per_tonne_co2e   = ship_energy_cost_per_year / solar_co2e_converted_tonnes

# -- Scale to reach 100 megatonne target --
# How large a solar field (in MW) is needed to destroy 100 Mt CH4/year?
solar_nameplate_for_target_mw = (target_tonnes / ch4_per_kwy) / (solar_nameplate_ratio * 1_000)
                                # MW nameplate needed (note: ~83 GW per spreadsheet annotation)
solar_acreage_for_target      = solar_nameplate_for_target_mw * solar_land_use_acres_per_mw

# =============================================================================
# SECTION 8 – LANDFILL SOLAR FIELD MODEL
# Solar panels installed on landfill, exploiting high local CH4 concentration.
# Higher construction cost but much higher conversion rate (500 ppm vs 2 ppm ambient).
# =============================================================================

landfill_nameplate_mw       = 100     # MW – example landfill solar field nameplate

landfill_acreage            = landfill_nameplate_mw * solar_land_use_acres_per_mw
landfill_available_kw       = landfill_nameplate_mw * 1_000 * solar_nameplate_ratio
landfill_energy_used_kwy    = landfill_available_kw  # kWy/year

# Annualised capital cost (with landfill construction premium)
landfill_annual_cap_cost    = (landfill_construction_premium
                               * (landfill_nameplate_mw * solar_cap_cost_per_mw_nameplate)
                               / solar_panel_lifetime_years) / landfill_energy_used_kwy
                              # $/kWy

# CH4 conversion is proportional to concentration relative to the reference
landfill_concentration_factor = (1_000 * landfill_ch4_concentration_ppm
                                 / ch4_reference_concentration_ppb)
                                # dimensionless scale factor; 500 ppm ÷ 2 ppb reference

landfill_ch4_converted_tonnes  = (landfill_energy_used_kwy * ch4_per_kwy
                                  * landfill_concentration_factor)
                                 # tonnes CH4/year – boosted by high local concentration
landfill_co2e_converted_tonnes = landfill_ch4_converted_tonnes * co2e_ratio

# Carbon credit revenue
landfill_revenue_ch4        = landfill_ch4_converted_tonnes  * credit_price_per_tonne_ch4
landfill_revenue_co2e       = landfill_co2e_converted_tonnes * credit_price_per_tonne_co2e

# Net economics
landfill_net_ch4            = landfill_revenue_ch4  - ship_energy_cost_per_year
landfill_net_co2e           = landfill_revenue_co2e - ship_energy_cost_per_year

landfill_cost_per_tonne_ch4  = ship_energy_cost_per_year / landfill_ch4_converted_tonnes
landfill_cost_per_tonne_co2e = ship_energy_cost_per_year / landfill_co2e_converted_tonnes

landfill_capital_cost        = landfill_nameplate_mw * solar_cap_cost_per_mw_nameplate
                               # $ – total upfront capital for the landfill solar field

# =============================================================================
# SECTION 9 – TROPOSPHERE / GLOBAL SUMMARY
# Back-of-envelope estimate of the scale of intervention needed to move
# the global atmospheric CH4 concentration by 1 ppm.
# Translated from the "Summary Master" sheet.
# =============================================================================

troposphere_volume_m3       = 1e18   # m³  – approximate volume of the troposphere

wh_to_remove_1ppm_per_m3    = 50     # Wh  – energy to remove 1 ppm CH4 from 1 m³ of air
                                     # (derived from smog-chamber experiments)

wh_to_remove_1ppm_troposphere = troposphere_volume_m3 * wh_to_remove_1ppm_per_m3
                                # Wh – total energy to reduce tropospheric CH4 by 1 ppm

wy_to_remove_1ppm_troposphere = wh_to_remove_1ppm_troposphere / hours_per_year
                                # Wy (watt-years) of continuous power required

nuclear_plant_output_wy     = 30_000_000   # Wy – approximate annual output of one nuclear plant
led_efficiency_multiplier   = 1_000        # LED devices are ~1000× more efficient than bulbs

nukes_needed                = wy_to_remove_1ppm_troposphere / nuclear_plant_output_wy
                              # number of nuclear plants required (without LED improvement)

years_to_run                = 10     # time horizon for the removal campaign
engineering_improvement     = 10     # further X improvement from better device engineering

# Total nukes accounting for LED efficiency and engineering improvement
nukes_with_improvements     = (nukes_needed / led_efficiency_multiplier
                               / engineering_improvement / years_to_run)

cost_per_micronuke          = 20_000_000   # $ – capital cost of a small modular / micro reactor
total_cost                  = nukes_needed * cost_per_micronuke
annual_cost                 = total_cost / years_to_run

# Solar equivalent
solar_wy_required           = wy_to_remove_1ppm_troposphere
solar_w_per_year            = solar_wy_required / years_to_run  # average watts sustained over campaign

# =============================================================================
# SECTION 10 – PRINT RESULTS
# =============================================================================

def fmt(value, prefix="$", decimals=2):
    """Format a number with thousands separators and optional prefix."""
    return f"{prefix}{value:,.{decimals}f}" if prefix else f"{value:,.{decimals}f}"

print("=" * 65)
print("METHANE DESTRUCTION COST MODEL – RESULTS")
print("=" * 65)

print("\n--- Conversion Ratio ---")
print(f"  CH4 destroyed per kWy:           {ch4_per_kwy} tonnes CH4")
print(f"  CO2e destroyed per kWy:          {co2e_per_kwy} tonnes CO2e")
print(f"  Energy per tonne CH4:            {j_per_tonne_ch4/kWh:,.0f} kWh")

print("\n--- Ship Ambient (single device, 100 kW, 250 ship-days/yr) ---")
print(f"  Energy used:                     {ship_energy_used_kwy:.3f} kWy")
print(f"  Energy cost/year:               {fmt(ship_energy_cost_per_year)}")
print(f"  CH4 converted:                   {ship_ch4_converted_tonnes:.4f} tonnes CH4")
print(f"  CO2e converted:                  {ship_co2e_converted_tonnes:.4f} tonnes CO2e")
print(f"  Revenue (CH4 credits):          {fmt(ship_revenue_ch4)}")
print(f"  Revenue (CO2e credits):         {fmt(ship_revenue_co2e)}")
print(f"  Net $ (CH4 basis):              {fmt(ship_net_ch4)}")
print(f"  Net $ (CO2e basis):             {fmt(ship_net_co2e)}")
print(f"  Cost per tonne CH4:             {fmt(ship_cost_per_tonne_ch4)}")
print(f"  Cost per tonne CO2e:            {fmt(ship_cost_per_tonne_co2e)}")

print(f"\n  --- Fleet scale ({plausible_equipped_fleet:,} ships, {avg_power_per_ship_mw} MW each) ---")
print(f"  Fleet CH4 converted/year:        {fleet_ch4_converted_tonnes:,.1f} tonnes")
print(f"  Fleet CO2e converted/year:       {fleet_co2e_converted_tonnes:,.1f} tonnes")
print(f"  Fleet total CO2e revenue:       {fmt(fleet_total_net_co2e)}")

print("\n--- Solar Field Ambient (100 MW nameplate) ---")
print(f"  Acreage required:                {solar_acreage:,.0f} acres")
print(f"  Energy used:                     {solar_energy_used_kwy:,.0f} kWy")
print(f"  CH4 converted:                   {solar_ch4_converted_tonnes:,.1f} tonnes")
print(f"  CO2e converted:                  {solar_co2e_converted_tonnes:,.1f} tonnes")
print(f"  Revenue (CH4):                  {fmt(solar_revenue_ch4)}")
print(f"  Revenue (CO2e):                 {fmt(solar_revenue_co2e)}")
print(f"  Cost per tonne CH4:             {fmt(solar_cost_per_tonne_ch4)}")
print(f"  MW nameplate for 100 Mt target:  {solar_nameplate_for_target_mw:,.0f} MW (~83 GW)")

print("\n--- Landfill Solar Field (100 MW nameplate, 500 ppm CH4) ---")
print(f"  Concentration factor vs ambient: {landfill_concentration_factor:,.0f}×")
print(f"  CH4 converted:                   {landfill_ch4_converted_tonnes:,.1f} tonnes")
print(f"  CO2e converted:                  {landfill_co2e_converted_tonnes:,.1f} tonnes")
print(f"  Revenue (CH4):                  {fmt(landfill_revenue_ch4)}")
print(f"  Revenue (CO2e):                 {fmt(landfill_revenue_co2e)}")
print(f"  Capital cost:                   {fmt(landfill_capital_cost)}")

print("\n--- Global / Troposphere Summary ---")
print(f"  Energy to remove 1 ppm tropospheric CH4:  {wy_to_remove_1ppm_troposphere:.3e} Wy")
print(f"  Nuclear plants required (no LED gains):   {nukes_needed:.3e}")
print(f"  With LED + engineering improvements:      {nukes_with_improvements:.3e}")
print(f"  Total cost estimate:                     {fmt(total_cost)}")
print(f"  Annual cost over {years_to_run} years:             {fmt(annual_cost)}")
print(f"  Solar power needed (averaged):            {solar_w_per_year:.3e} W")
print("=" * 65)
