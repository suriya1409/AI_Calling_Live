# Payment Intent Tracking - Updated Feature

## Date: February 17, 2026

## Overview
The system now captures detailed borrower intent from AI call analysis, categorizing responses into 5 distinct categories instead of simple Yes/No. This provides much better insight into borrower behavior and helps prioritize follow-ups.

## Payment Confirmation Categories

### 1. 🟢 **Paid**
- **Meaning:** Borrower has already made the payment
- **Badge Color:** Dark Green (#d1fae5)
- **Follow-up:** No follow-up needed (empty date)
- **Priority:** Low - Payment received

### 2. 🟢 **Will Pay**
- **Meaning:** Borrower commits to paying (may or may not mention specific date)
- **Badge Color:** Light Green (#dcfce7)
- **Follow-up:** 
  - If date mentioned: Use that date
  - If no date: 3 days from call
- **Priority:** Medium - Monitor commitment

### 3. 🟠 **Needs Extension**
- **Meaning:** Borrower requests more time to pay
- **Badge Color:** Orange (#fed7aa)
- **Follow-up:** 3 days from call
- **Priority:** Medium-High - Requires negotiation

### 4. 🔴 **Dispute**
- **Meaning:** Borrower disputes the amount or loan
- **Badge Color:** Red (#fee2e2)
- **Follow-up:** 7 days from call (allows time for resolution)
- **Priority:** High - Requires immediate attention

### 5. ⚪ **No Response**
- **Meaning:** Borrower didn't engage or provide clear answer
- **Badge Color:** Gray (#e5e7eb)
- **Follow-up:** Next day (1 day from call)
- **Priority:** High - Requires re-contact

## Follow-up Date Logic

The system automatically sets follow-up dates based on intent:

| Intent | Payment Date Mentioned | Follow-up Date |
|--------|----------------------|----------------|
| Paid | Any | Empty (no follow-up needed) |
| Will Pay | Yes | The mentioned date |
| Will Pay | No | +3 days |
| Needs Extension | Yes | The mentioned date |
| Needs Extension | No | +3 days |
| Dispute | Any | +7 days |
| No Response | Any | +1 day |

## How AI Determines Intent

The Gemini AI analyzes the conversation and classifies intent based on:

1. **Paid:** Borrower explicitly states payment is complete
   - "I already paid yesterday"
   - "Payment was made on the 15th"

2. **Will Pay:** Borrower commits to future payment
   - "I'll pay by February 20th"
   - "I will make the payment this week"

3. **Needs Extension:** Borrower requests more time
   - "Can I get a few more days?"
   - "I need an extension until next month"

4. **Dispute:** Borrower questions or disputes the debt
   - "This amount is wrong"
   - "I don't owe this money"
   - "There's been a mistake"

5. **No Response:** No clear commitment or engagement
   - Borrower doesn't answer clearly
   - Call goes to voicemail
   - Borrower hangs up

## Visual Guide

### Reports Table Display

```
┌─────────────────────────────────────────────────────────┐
│ PAYMENT CONF.        │ FOLLOW UP DATE │ PRIORITY        │
├─────────────────────────────────────────────────────────┤
│ 🟢 Paid              │ -              │ ✓ Complete      │
│ 🟢 Will Pay          │ 2026-02-20     │ ⚠ Monitor       │
│ 🟠 Needs Extension   │ 2026-02-20     │ ⚠⚠ Negotiate    │
│ 🔴 Dispute           │ 2026-02-24     │ ⚠⚠⚠ Urgent     │
│ ⚪ No Response       │ 2026-02-18     │ ⚠⚠⚠ Re-contact │
└─────────────────────────────────────────────────────────┘
```

## Backend Changes

### Updated Logic (`backend/app/ai_calling/views.py`)

```python
# Extract intent from AI analysis
intent = ai_analysis.get("intent", "No Response")

# Set payment confirmation to intent value
payment_confirmation = intent

# Smart follow-up date calculation
if payment_date:
    follow_up_date = payment_date
elif intent in ["Will Pay", "Needs Extension"]:
    follow_up_date = current_time + 3 days
elif intent == "Dispute":
    follow_up_date = current_time + 7 days
elif intent == "Paid":
    follow_up_date = "" (no follow-up)
else:  # No Response
    follow_up_date = current_time + 1 day
```

## Frontend Changes

### Color-Coded Badges (`frontend/js/app.js`)

Each intent has a distinct visual style:
- **Paid:** Dark green background
- **Will Pay:** Light green background
- **Needs Extension:** Orange background
- **Dispute:** Red background
- **No Response:** Gray background

## CSV Export

The exported CSV now includes:
- `payment_confirmation`: One of the 5 intent categories
- `follow_up_date`: Automatically calculated date

## Use Cases

### 1. Daily Follow-up List
Filter by follow-up date = today to see who needs contact

### 2. Priority Queue
Sort by intent:
1. Dispute (highest priority)
2. No Response
3. Needs Extension
4. Will Pay
5. Paid (lowest priority)

### 3. Performance Metrics
Track conversion rates:
- How many "Will Pay" actually pay?
- How many "No Response" convert on second call?
- Average resolution time for "Dispute"

## Testing Scenarios

### Test Case 1: Borrower Commits with Date
**Conversation:** "I will pay on February 25th"
- **Expected Intent:** Will Pay
- **Expected Follow-up:** 2026-02-25

### Test Case 2: Borrower Needs Extension
**Conversation:** "Can I get more time? I'll pay next week"
- **Expected Intent:** Needs Extension
- **Expected Follow-up:** +3 days

### Test Case 3: Borrower Disputes
**Conversation:** "This amount is incorrect, I don't owe this"
- **Expected Intent:** Dispute
- **Expected Follow-up:** +7 days

### Test Case 4: No Clear Response
**Conversation:** Borrower doesn't commit or hangs up
- **Expected Intent:** No Response
- **Expected Follow-up:** +1 day

### Test Case 5: Already Paid
**Conversation:** "I already paid this last week"
- **Expected Intent:** Paid
- **Expected Follow-up:** (empty)

## Benefits

1. **Better Prioritization:** Know which borrowers need urgent attention
2. **Smarter Follow-ups:** Different timelines for different situations
3. **Clear Insights:** Understand borrower behavior at a glance
4. **Improved Collections:** Focus on high-priority cases first
5. **Performance Tracking:** Measure success rates by intent category

## Next Steps

1. Make test calls with different scenarios
2. Verify AI correctly categorizes intents
3. Check follow-up dates are calculated correctly
4. Export CSV to verify data structure
5. Use Reports section to prioritize daily work

Enjoy the enhanced tracking! 🚀
