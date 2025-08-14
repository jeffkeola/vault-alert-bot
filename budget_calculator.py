#!/usr/bin/env python3
"""
Budget Calculator for CoinGlass API Usage
Calculates optimal check intervals for different pricing plans
"""

def calculate_api_usage(vaults=13, check_interval_minutes=5):
    """Calculate API calls per hour/day/month"""
    
    # API calls per vault check
    calls_per_vault = 1  # One call to get positions per vault
    calls_per_check = vaults * calls_per_vault
    
    # Time calculations
    checks_per_hour = 60 / check_interval_minutes
    checks_per_day = checks_per_hour * 24
    checks_per_month = checks_per_day * 30
    
    # API usage calculations
    calls_per_hour = calls_per_check * checks_per_hour
    calls_per_day = calls_per_check * checks_per_day
    calls_per_month = calls_per_check * checks_per_month
    
    return {
        'vaults': vaults,
        'check_interval_minutes': check_interval_minutes,
        'calls_per_check': calls_per_check,
        'checks_per_hour': checks_per_hour,
        'calls_per_hour': calls_per_hour,
        'calls_per_day': calls_per_day,
        'calls_per_month': calls_per_month,
        'calls_per_minute_avg': calls_per_hour / 60
    }

def find_optimal_intervals():
    """Find optimal check intervals for different CoinGlass plans"""
    
    plans = {
        'Hobbyist': {'cost': 29, 'requests_per_min': 30},
        'Startup': {'cost': 79, 'requests_per_min': 80},
        'Standard': {'cost': 299, 'requests_per_min': 300},
        'Professional': {'cost': 699, 'requests_per_min': 1200}
    }
    
    check_intervals = [1, 2, 3, 5, 10, 15, 30, 60]  # minutes
    
    print("🎯 CoinGlass API Usage Calculator")
    print("=" * 50)
    print(f"Tracking {13} vaults\n")
    
    for interval in check_intervals:
        usage = calculate_api_usage(vaults=13, check_interval_minutes=interval)
        
        print(f"📊 Check Interval: {interval} minute(s)")
        print(f"   • API calls per check: {usage['calls_per_check']}")
        print(f"   • Average calls/minute: {usage['calls_per_minute_avg']:.2f}")
        print(f"   • Daily API calls: {usage['calls_per_day']:,.0f}")
        print(f"   • Monthly API calls: {usage['calls_per_month']:,.0f}")
        
        # Check which plans work
        compatible_plans = []
        for plan_name, plan_data in plans.items():
            if usage['calls_per_minute_avg'] <= plan_data['requests_per_min']:
                compatible_plans.append(f"{plan_name} (${plan_data['cost']}/mo)")
        
        if compatible_plans:
            print(f"   ✅ Compatible plans: {', '.join(compatible_plans)}")
        else:
            print(f"   ❌ Exceeds all plan limits")
        print()

def recommend_budget_setup():
    """Recommend optimal setup for budget-conscious users"""
    
    print("💡 BUDGET RECOMMENDATIONS")
    print("=" * 40)
    
    # Startup plan analysis
    startup_usage = calculate_api_usage(vaults=13, check_interval_minutes=5)
    print(f"🎯 Startup Plan ($79/month) - 5min intervals:")
    print(f"   • API usage: {startup_usage['calls_per_minute_avg']:.2f}/min (limit: 80/min)")
    print(f"   • Utilization: {(startup_usage['calls_per_minute_avg']/80)*100:.1f}%")
    print(f"   • Safety margin: Very comfortable")
    print()
    
    # Hobbyist plan analysis  
    hobbyist_usage = calculate_api_usage(vaults=13, check_interval_minutes=15)
    print(f"💰 Hobbyist Plan ($29/month) - 15min intervals:")
    print(f"   • API usage: {hobbyist_usage['calls_per_minute_avg']:.2f}/min (limit: 30/min)")
    print(f"   • Utilization: {(hobbyist_usage['calls_per_minute_avg']/30)*100:.1f}%")
    print(f"   • Safety margin: Comfortable for learning")
    print()
    
    print("🎯 RECOMMENDATIONS:")
    print()
    print("📚 For Learning/Testing (Hobbyist $29/month):")
    print("   • 15-minute check intervals")
    print("   • Still catches major moves")
    print("   • Great for understanding patterns")
    print("   • Low risk investment")
    print()
    print("🚀 For Serious Tracking (Startup $79/month):")
    print("   • 5-minute check intervals") 
    print("   • Catches most trading opportunities")
    print("   • Good balance of cost vs performance")
    print("   • Recommended for active monitoring")
    print()
    print("⚡ For Active Trading (Standard $299/month):")
    print("   • 1-2 minute check intervals")
    print("   • Near real-time detection")
    print("   • For high-frequency opportunities")

if __name__ == "__main__":
    find_optimal_intervals()
    print()
    recommend_budget_setup()