import pandas as pd
from datetime import datetime, timedelta

def categorize_customer(row):
    """
    Categorize customer based on acstatus from Excel.
    Returns: SMA0, SMA1, SMA2, SMA3, or NPA
    """
    acstatus = str(row.get('acstatus', '')).upper().strip()
    
    if 'SMA0' in acstatus:
        return 'SMA0'
    elif 'SMA1' in acstatus:
        return 'SMA1'
    elif 'SMA2' in acstatus:
        return 'SMA2'
    elif 'SMA3' in acstatus:
        return 'SMA3'
    elif 'NPA' in acstatus:
        return 'NPA'
    else:
        # Default fallback or try to infer from other statuses if needed
        return 'SMA0'


def categorize_by_due_date(row):
    """
    Categorize customer based on days until due date.
    Due date = LAST DUE REVD DATE + 30 days
    Returns: More_than_7_days, 1-7_days, or Today
    """
    try:
        # Get last payment date
        raw_date = row.get('LAST DUE REVD DATE')
        if pd.isna(raw_date):
            return 'Unknown'
        
        # Convert to datetime (handle if already datetime or needs parsing)
        if isinstance(raw_date, (datetime, pd.Timestamp)):
            last_due_date = raw_date
        else:
            last_due_date = pd.to_datetime(raw_date, dayfirst=True, errors='coerce')
        
        if pd.isna(last_due_date):
            return 'Date_Format_Error'
        
        # Calculate due date (last payment + 30 days)
        due_date = last_due_date + timedelta(days=30)
        
        # Get current date (without time)
        current_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Calculate days until due
        days_left = (due_date - current_date).days
        
        # Categorize
        if days_left > 7:
            return 'More_than_7_days'
        elif 1 <= days_left <= 7:
            return '1-7_days'
        else:
            # 0 or negative (today or overdue)
            return 'Today'
    except Exception as e:
        return 'Parse_Error'
