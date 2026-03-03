# Quick Reference: Payment Intent Categories

## 🎯 5 Intent Categories

| Intent | Color | Icon | Follow-up | Action Required |
|--------|-------|------|-----------|-----------------|
| **Paid** | 🟢 Dark Green | ✓ | None | Archive/Close |
| **Will Pay** | 🟢 Light Green | 📅 | Date or +3 days | Monitor |
| **Needs Extension** | 🟠 Orange | ⏰ | +3 days | Negotiate |
| **Dispute** | 🔴 Red | ⚠️ | +7 days | Escalate |
| **No Response** | ⚪ Gray | 📞 | +1 day | Re-contact |

## 📊 Priority Levels

### 🔴 URGENT (Today)
- **Dispute** - Requires immediate resolution
- **No Response** - Second attempt needed

### 🟠 HIGH (This Week)
- **Needs Extension** - Negotiate terms
- **Will Pay** (no date) - Confirm commitment

### 🟢 MEDIUM (Monitor)
- **Will Pay** (with date) - Track until payment date

### ✅ LOW (Complete)
- **Paid** - Verify and close

## 🗓️ Follow-up Timeline

```
TODAY
  │
  ├─ No Response → +1 day → TOMORROW
  │
  ├─ Will Pay (no date) → +3 days → 3 DAYS LATER
  │
  ├─ Needs Extension → +3 days → 3 DAYS LATER
  │
  ├─ Dispute → +7 days → NEXT WEEK
  │
  └─ Paid → No follow-up → DONE ✓
```

## 💡 Quick Actions

### When you see "Paid" 🟢
- ✓ Verify payment in system
- ✓ Update records
- ✓ Send confirmation
- ✓ Close case

### When you see "Will Pay" 🟢
- ✓ Note the commitment date
- ✓ Set reminder
- ✓ Follow up on date
- ✓ Send payment link if needed

### When you see "Needs Extension" 🟠
- ✓ Review borrower history
- ✓ Assess extension request
- ✓ Negotiate new terms
- ✓ Document agreement

### When you see "Dispute" 🔴
- ✓ Review loan details
- ✓ Gather documentation
- ✓ Escalate to supervisor
- ✓ Prepare resolution plan

### When you see "No Response" ⚪
- ✓ Try different contact method
- ✓ Call at different time
- ✓ Send SMS/email
- ✓ Update contact attempts

## 📈 Success Metrics

Track these conversion rates:
- **Will Pay → Paid:** Target 70%+
- **Needs Extension → Paid:** Target 50%+
- **No Response → Any Response:** Target 60%+
- **Dispute → Resolved:** Target 80%+

## 🎨 Visual Legend

### Badge Colors in Reports Table

```
┌──────────────────────┐
│  🟢 Paid             │ ← Dark Green = Complete
├──────────────────────┤
│  🟢 Will Pay         │ ← Light Green = Committed
├──────────────────────┤
│  🟠 Needs Extension  │ ← Orange = Attention Needed
├──────────────────────┤
│  🔴 Dispute          │ ← Red = Urgent Action
├──────────────────────┤
│  ⚪ No Response      │ ← Gray = No Engagement
└──────────────────────┘
```

## 📋 Daily Workflow

### Morning Routine
1. Open Reports section
2. Sort by Follow-up Date = Today
3. Prioritize: Dispute → No Response → Needs Extension → Will Pay
4. Make calls in priority order

### After Each Call
1. System auto-updates intent
2. Follow-up date auto-calculated
3. Check Reports to see updates
4. Move to next borrower

### End of Day
1. Export CSV for records
2. Review tomorrow's follow-ups
3. Plan next day's priorities

## 🔍 Filtering Tips

### In Reports Section
- **Click column headers** to sort
- **Look for colors** to identify priorities
- **Check follow-up dates** for today's tasks
- **Use Refresh** to get latest data

### In CSV Export
- Filter by `payment_confirmation` column
- Sort by `follow_up_date` column
- Create pivot tables for analytics
- Track trends over time

---

**Print this page and keep it handy for quick reference!** 📌
