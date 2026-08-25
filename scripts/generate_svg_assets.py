#!/usr/bin/env python3
"""
Master SVG Asset Generation and Verification Script
Builds all standalone SVG diagram assets and sales visual illustrations.
"""
import sys
from gen_latency_waterfall import build_latency_waterfall
from gen_decision_tree import build_decision_tree
from gen_enterprise_logos import build_enterprise_logos
from gen_battlecard_matrix import build_battlecard_matrix
from gen_sales_illustrations import (
    build_cascade_vs_duplex,
    build_cost_advantage_10x,
    build_sub_500ms_delight,
    build_india_market_inflection,
)
from verify_all_assets import verify_all

def main():
    print("=" * 80)
    print("GENERATING ALL PRESENTATION SVG ASSETS")
    print("=" * 80)
    build_latency_waterfall()
    build_decision_tree()
    build_enterprise_logos()
    build_battlecard_matrix()
    build_cascade_vs_duplex()
    build_cost_advantage_10x()
    build_sub_500ms_delight()
    build_india_market_inflection()
    
    print("\nRUNNING VERIFICATION SUITE...")
    result = verify_all()
    sys.exit(result)

if __name__ == "__main__":
    main()
