#!/usr/bin/env python3
"""MSCI USA IMI / USFASTD 60 GICS industry labels (Barra US TMT, Mar 2015)."""

from __future__ import annotations

import re

# Official GICS industry names (user-provided, USFASTD / USE4D).
GICS_INDUSTRY_NAMES = (
    'Oil and Gas Drilling',
    'Oil and Gas Equipment and Services',
    'Oil and Gas Exploration and Production',
    'Oil Gas and Consumable Fuels',
    'Chemicals',
    'Specialty Chemicals',
    'Construction Materials',
    'Containers and Packaging',
    'Paper and Forest Products',
    'Aluminum Steel',
    'Precious Metals Gold Mining',
    'Aerospace and Defense',
    'Construction and Farm Machinery',
    'Industrial Machinery',
    'Building Products',
    'Trading Companies and Distributors',
    'Construction and Engineering',
    'Electrical Equipment',
    'Industrial Conglomerates',
    'Commercial and Professional Services',
    'Airlines',
    'Transportation Air Freight and Marine',
    'Road and Rail',
    'Automobiles and Components',
    'Household Durables (non-Homebuildng)',
    'Homebuilding',
    'Leisure Products Textiles Apparel and Luxury',
    'Hotels Leisure and Consumer Services',
    'Restaurants',
    'Media',
    'Distributors Multiline Retail',
    'Internet and Catalog Retail',
    'Apparel and Textiles',
    'Specialty Stores',
    'Specialty Retail',
    'Household and Personal Products',
    'Food and Staples Retailing',
    'Food Products',
    'Beverages Tobacco',
    'Health Care Equipment and Technology',
    'Managed Health Care',
    'Health Care Providers (non-HMO)',
    'Biotechnology Life Sciences',
    'Pharmaceuticals',
    'Banks',
    'Diversified Financials',
    'Life Health and Multi-line Insurance',
    'Insurance Brokers and Reinsurance',
    'Real Estate',
    'Semiconductor Equipment',
    'Semiconductors',
    'Internet Software and IT Services',
    'Software',
    'Communications Equipment',
    'Computers Electronics',
    'Diversified Telecommunication Services',
    'Wireless Telecommunication Services',
    'Electric Utilities',
    'Gas Utilities',
    'Multi-Utilities Water Utilities Power',
)

# Known overrides where Barra slug != naive slugify.
SLUG_OVERRIDES = {
    'oil and gas drilling': 'usfastd_oildrill',
    'oil and gas equipment and services': 'usfastd_oilgas',
    'oil and gas exploration and production': 'usfastd_oilgas',
    'oil gas and consumable fuels': 'usfastd_oilgas',
    'aluminum steel': 'usfastd_steel',
    'precious metals gold mining': 'usfastd_gold',
    'aerospace and defense': 'usfastd_aerodef',
    'construction and farm machinery': 'usfastd_machinery',
    'construction and engineering': 'usfastd_cnsteng',
    'commercial and professional services': 'usfastd_comsvcs',
    'transportation air freight and marine': 'usfastd_transport',
    'road and rail': 'usfastd_roadrl',
    'automobiles and components': 'usfastd_autocomp',
    'household durables (non-homebuildng)': 'usfastd_condur',
    'leisure products textiles apparel and luxury': 'usfastd_apparel',
    'hotels leisure and consumer services': 'usfastd_hotels',
    'distributors multiline retail': 'usfastd_splret',
    'internet and catalog retail': 'usfastd_internet',
    'health care equipment and technology': 'usfastd_meddev',
    'managed health care': 'usfastd_hlthsvcs',
    'health care providers (non-hmo)': 'usfastd_hlthsvcs',
    'biotechnology life sciences': 'usfastd_biolife',
    'diversified financials': 'usfastd_divfin',
    'life health and multi-line insurance': 'usfastd_insurnce',
    'insurance brokers and reinsurance': 'usfastd_insurnce',
    'real estate': 'usfastd_realest',
    'semiconductor equipment': 'usfastd_semieqp',
    'internet software and it services': 'usfastd_internet',
    'diversified telecommunication services': 'usfastd_telecom',
    'wireless telecommunication services': 'usfastd_wireless',
    'multi-utilities water utilities power': 'usfastd_multutil',
}


def gics_to_usfastd_slug(label: str) -> str:
    key = str(label).strip().lower()
    if key in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[key]
    slug = re.sub(r'[^a-z0-9]+', '', key.replace(' and ', '').replace(' ', ''))[:12]
    return f'usfastd_{slug}' if slug else 'usfastd_misc'


def all_gics_usfastd_columns() -> list[str]:
    return sorted({gics_to_usfastd_slug(n) for n in GICS_INDUSTRY_NAMES} | {'usfastd_misc'})
