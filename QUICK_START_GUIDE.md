# Quick Start Guide - Payment Confirmation & Follow-up Feature

## What's New? 🎉

After making a call, the system now automatically:
1. ✅ Detects if the borrower mentioned a payment date
2. ✅ Updates the borrower record with payment confirmation (Yes/No)
3. ✅ Sets a follow-up date (mentioned date or next day)
4. ✅ Shows all this information in the Reports section
5. ✅ Allows you to export everything to CSV

## How to Use

### Step 1: Make Calls
1. Go to Dashboard
2. Click on any time period card (Today, 1-7 Days, More than 7 Days)
3. Click "Make call" button
4. Wait for calls to complete

### Step 2: View Reports
1. Click on "Reports" in the sidebar
2. You'll see a table with all borrowers including:
   - Payment Confirmation (Yes/No badge)
   - Follow-up Date
   - All other borrower details

### Step 3: Export Data
1. In the Reports section, click "Export CSV" button
2. A CSV file will download with all updated data
3. Open in Excel or Google Sheets

## What the System Does Automatically

### When Borrower Says "I'll pay on February 20th":
- ✅ Payment Confirmation: **Yes** (Green badge)
- ✅ Follow-up Date: **2026-02-20**

### When Borrower Doesn't Mention a Date:
- ✅ Payment Confirmation: **No** (Red badge)
- ✅ Follow-up Date: **Next day** (e.g., 2026-02-18)

## Reports Table Columns

| Column | Description |
|--------|-------------|
| NO. | Borrower ID |
| BORROWER | Borrower name |
| AMOUNT | Loan amount |
| MOBILE | Phone number |
| EMI | EMI amount |
| LANGUAGE | Preferred language |
| **PAYMENT CONF.** | **Yes/No badge** |
| **FOLLOW UP DATE** | **Date to follow up** |
| LAST DUE/REVD DATE | Last payment/due date |

## CSV Export

The exported CSV includes all fields:
- NO, BORROWER, AMOUNT, EMI, MOBILE, LANGUAGE
- Payment_Category, Due_Date_Category
- DUE_DATE, LAST_PAID_DATE
- call_completed, **payment_confirmation**, **follow_up_date**
- ai_summary

## Tips

1. **Refresh Data**: Click "Refresh Data" button to get latest updates
2. **Auto-Update**: Reports table updates automatically after calls complete
3. **Color Codes**: 
   - 🟢 Green = Payment confirmed
   - 🔴 Red = No payment commitment
   - ⚪ Gray = Call not made yet

## Troubleshooting

**Q: Reports table is empty?**
- A: Upload a borrower file first, or click "Refresh Data"

**Q: Payment confirmation shows "-"?**
- A: Call hasn't been made yet for that borrower

**Q: CSV export not working?**
- A: Make sure you're logged in and have data uploaded

## Next Steps

1. Make calls to borrowers
2. Check Reports section to see payment confirmations
3. Export CSV for record-keeping
4. Use follow-up dates to plan next contact

Enjoy! 🚀
