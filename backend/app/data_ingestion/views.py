from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Body
import pandas as pd
import io
import time
from datetime import datetime
from typing import Optional, List, Dict
from .utils import Config, logger, validate_file_size, normalize_column_names, optimize_dataframe, sanitize_for_json
from .service import categorize_customer, categorize_by_due_date
from app.table_models.borrowers_table import (
    get_all_borrowers,
    get_borrower_by_no,
    bulk_upsert_borrowers,
    update_borrower,
    delete_borrower,
    delete_all_borrowers,
    get_global_borrower_stats
)
from app.auth.utils import get_current_user

router = APIRouter()

@router.get("/")
def read_root():
    """Health check endpoint with system status."""
    return {
        "status": "running",
        "message": "Data Ingestion & CRUD API: User Isolated",
        "version": "4.2",
        "endpoints": {
            "upload": "POST /data (multipart/form-data)",
            "list": "GET /borrowers",
            "get": "GET /borrowers/{id}",
            "update": "PUT /borrowers/{id}",
            "delete": "DELETE /borrowers/{id}",
            "delete_all": "DELETE /delete_all",
            "global_stats": "GET /debug/global_stats (Debug only)"
        }
    }

@router.get("/debug/global_stats")
async def get_all_db_stats(current_user: dict = Depends(get_current_user)):
    """
    DEBUG ONLY: Check total records across all users to verify isolation is working.
    """
    stats = await get_global_borrower_stats()
    return {
        "message": "Isolation Audit: Total records across all users in MongoDB",
        "current_user_id": str(current_user["_id"]),
        "stats": stats
    }

# ==========================================
# DATA INGESTION (BULK UPLOAD)
# ==========================================

@router.post("/data")
async def unified_data_endpoint(
    file: UploadFile = File(None),
    time_period: Optional[str] = None,
    include_details: bool = False,
    current_user: dict = Depends(get_current_user)
):
    """
    **UPLOAD & ANALYSIS** - Process dataset and save to MongoDB borrowers collection with User Isolation.
    """
    start_time = time.time()
    user_id = str(current_user["_id"])
    
    if file:
        logger.info(f"Processing dataset upload for user {user_id}: {file.filename}")
        
        # Validate file size
        if not validate_file_size(file):
             raise HTTPException(status_code=400, detail="File too large")

        # Validate file type
        if not any(file.filename.endswith(ext) for ext in Config.ALLOWED_EXTENSIONS):
            raise HTTPException(status_code=400, detail="Invalid file type")
        
        try:
            contents = await file.read()
            if file.filename.endswith('.csv'):
                df = pd.read_csv(io.BytesIO(contents))
            else:
                df = pd.read_excel(io.BytesIO(contents), engine='openpyxl')
            
            # Normalize and Optimize
            df = normalize_column_names(df)
            df = optimize_dataframe(df)
            
            # Apply standard categorizations
            df['Payment_Category'] = df.apply(categorize_customer, axis=1)
            df['Due_Date_Category'] = df.apply(categorize_by_due_date, axis=1)
            
            # Handle NaT/NaN for MongoDB
            df = df.replace({pd.NA: None, pd.NaT: None})
            df = df.where(pd.notnull(df), None)
            
            # Convert to records
            records = df.to_dict('records')
            
            # Persist in MongoDB with User Isolation
            await bulk_upsert_borrowers(user_id, records)
            
            logger.info(f"Successfully ingested {len(records)} borrowers for user {user_id}")
            
        except Exception as e:
            logger.error(f"Ingestion error for user {user_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise HTTPException(status_code=500, detail=str(e))
    
    # Fetch borrowers for the current user only
    borrowers = await get_all_borrowers(user_id, limit=2000)
    
    # Calculate KPIs and Breakdown
    total_arrears = 0
    by_category = {
        "More_than_7_days": [],
        "1-7_days": [],
        "Today": []
    }
    
    for b in borrowers:
        # Calculate total arrears
        amount = b.get("AMOUNT", 0)
        if amount is not None:
            try:
                total_arrears += float(amount)
            except: pass
        
        # Group by due date category
        due_cat = b.get("Due_Date_Category", "Today")
        if due_cat in by_category:
            by_category[due_cat].append(b)
        else:
            by_category["Today"].append(b) # Default fallback
            
    response_data = {
        "status": "success",
        "kpis": {
            "total_borrowers": len(borrowers),
            "total_arrears": round(total_arrears, 2)
        },
        "detailed_breakdown": {
            "by_due_date_category": by_category
        },
        "uploaded": file is not None,
        "processing_time": round(time.time() - start_time, 2)
    }
    
    return sanitize_for_json(response_data)

# ==========================================
# BORROWERS CRUD OPERATIONS (Standalone API)
# ==========================================

@router.get("/borrowers", response_model=List[Dict])
async def list_borrowers_api(
    limit: int = 100, 
    skip: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """List borrowers for the current user"""
    user_id = str(current_user["_id"])
    borrowers = await get_all_borrowers(user_id, limit=limit, skip=skip)
    return sanitize_for_json(borrowers)

@router.delete("/delete_all")
async def delete_all_borrowers_api(current_user: dict = Depends(get_current_user)):
    """Delete all borrower records for the current user"""
    user_id = str(current_user["_id"])
    count = await delete_all_borrowers(user_id)
    return {
        "status": "success", 
        "message": f"Successfully deleted {count} borrower records for you",
        "deleted_count": count
    }

@router.get("/borrowers/{borrower_no}")
async def get_borrower_api(borrower_no: str, current_user: dict = Depends(get_current_user)):
    """Get details of a specific borrower by their NO identifier"""
    user_id = str(current_user["_id"])
    borrower = await get_borrower_by_no(user_id, borrower_no)
    if not borrower:
        raise HTTPException(status_code=404, detail="Borrower not found in your dataset")
    return sanitize_for_json(borrower)

@router.put("/borrowers/{borrower_no}")
async def update_borrower_api(
    borrower_no: str, 
    update_data: Dict = Body(...),
    current_user: dict = Depends(get_current_user)
):
    """Update borrower information for the current user"""
    user_id = str(current_user["_id"])
    success = await update_borrower(user_id, borrower_no, update_data)
    if not success:
        raise HTTPException(status_code=404, detail="Borrower not found in your dataset")
        
    return {"status": "success", "message": "Borrower updated"}

@router.delete("/borrowers/{borrower_no}")
async def delete_borrower_api(borrower_no: str, current_user: dict = Depends(get_current_user)):
    """Delete a borrower record for the current user"""
    user_id = str(current_user["_id"])
    success = await delete_borrower(user_id, borrower_no)
    if not success:
        raise HTTPException(status_code=404, detail="Borrower not found in your dataset")
        
    return {"status": "success", "message": "Borrower deleted"}

@router.get("/export/csv")
async def export_borrowers_csv(current_user: dict = Depends(get_current_user)):
    """Export all borrower data as CSV for the current user"""
    from fastapi.responses import StreamingResponse
    import csv
    from io import StringIO
    
    user_id = str(current_user["_id"])
    borrowers = await get_all_borrowers(user_id, limit=10000)
    
    if not borrowers:
        raise HTTPException(status_code=404, detail="No borrower data found")
    
    # Define CSV columns
    columns = [
        "NO", "BORROWER", "AMOUNT", "EMI", "MOBILE", "LANGUAGE",
        "Payment_Category", "Due_Date_Category", "DUE_DATE", "LAST_PAID_DATE",
        "LAST DUE REVD DATE", "call_completed", "payment_confirmation", "follow_up_date", "ai_summary"
    ]
    
    # Create CSV in memory
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    
    for borrower in borrowers:
        # Prepare row data
        row = {}
        for col in columns:
            value = borrower.get(col, "")
            # Handle boolean values
            if isinstance(value, bool):
                value = "Yes" if value else "No"
            # Handle None values
            if value is None:
                value = ""
            row[col] = value
        writer.writerow(row)
    
    # Prepare response
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=borrowers_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    )
