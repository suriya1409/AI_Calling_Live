from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Body
import pandas as pd
import io
import time
from typing import Optional, List, Dict
from .utils import Config, logger, validate_file_size, normalize_column_names, optimize_dataframe
from .service import categorize_customer, categorize_by_due_date
from app.db import db
from app.auth.utils import get_current_user

router = APIRouter()

@router.get("/")
def read_root():
    """Health check endpoint with system status."""
    return {
        "status": "running",
        "message": "Data Ingestion & CRUD API - MongoDB Integrated",
        "version": "4.0",
        "endpoints": {
            "upload": "POST /data (multipart/form-data)",
            "list": "GET /borrowers",
            "get": "GET /borrowers/{id}",
            "update": "PUT /borrowers/{id}",
            "delete": "DELETE /borrowers/{id}"
        }
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
    **UPLOAD & ANALYSIS** - Process dataset and save to MongoDB borrowers collection.
    """
    start_time = time.time()
    
    if file:
        logger.info(f"Processing dataset upload: {file.filename}")
        
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
            
            # --- FIX: Handle NaT (Not a Time) and NaN (Not a Number) for MongoDB ---
            # MongoDB driver cannot serialize Pandas NaT/NaN objects
            df = df.replace({pd.NA: None, pd.NaT: None})
            df = df.where(pd.notnull(df), None)
            
            # Convert to records for MongoDB
            records = df.to_dict('records')
            
            # Persist in MongoDB
            db.bulk_upsert_borrowers(records)
            
            logger.info(f"Successfully ingested {len(records)} borrowers into MongoDB")
            
        except Exception as e:
            logger.error(f"Ingestion error: {e}")
            # Log the full traceback for debugging if needed
            import traceback
            logger.error(traceback.format_exc())
            raise HTTPException(status_code=500, detail=str(e))
    
    # Fetch all borrowers to build the response
    borrowers = db.get_all_borrowers(limit=2000)
    
    # Calculate KPIs and Breakdown
    total_arrears = 0
    by_category = {
        "More_than_7_days": [],
        "1-7_days": [],
        "Today": []
    }
    
    import math

    for b in borrowers:
        # Convert _id to string for JSON serialization
        if "_id" in b: b["_id"] = str(b["_id"])
        
        # Sanitize float values (NaN/Inf) which are not JSON compliant
        for key, value in b.items():
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                b[key] = None

        # Calculate total arrears
        amount = b.get("AMOUNT", 0)
        if amount is not None:
            total_arrears += amount
        
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
    
    return response_data

# ==========================================
# BORROWERS CRUD OPERATIONS
# ==========================================

@router.get("/borrowers", response_model=List[Dict])
async def list_borrowers(
    limit: int = 100, 
    skip: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """List borrowers with optional filtering"""
    # Fetch from Mongo
    borrowers = db.get_all_borrowers(limit=limit)
    for b in borrowers:
        b["_id"] = str(b["_id"])
    return borrowers

@router.get("/borrowers/{borrower_no}")
async def get_borrower(borrower_no: str, current_user: dict = Depends(get_current_user)):
    """Get details of a specific borrower by their NO identifier"""
    borrower = db.get_borrower_by_id(borrower_no)
    if not borrower:
        raise HTTPException(status_code=404, detail="Borrower not found")
    borrower["_id"] = str(borrower["_id"])
    return borrower

@router.put("/borrowers/{borrower_no}")
async def update_borrower(
    borrower_no: str, 
    update_data: Dict = Body(...),
    current_user: dict = Depends(get_current_user)
):
    """Update borrower information (handles string or int NO)"""
    collection = db.get_collection("borrowers")
    
    # Prepare query to match both string and integer
    query_ids = [str(borrower_no)]
    try:
        query_ids.append(int(borrower_no))
    except: pass
    
    result = collection.update_one({"NO": {"$in": query_ids}}, {"$set": update_data})
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Borrower not found")
        
    return {"status": "success", "modified_count": result.modified_count}

@router.delete("/borrowers/{borrower_no}")
async def delete_borrower(borrower_no: str, current_user: dict = Depends(get_current_user)):
    """Delete a borrower record (handles string or int NO)"""
    collection = db.get_collection("borrowers")
    
    # Prepare query to match both string and integer
    query_ids = [str(borrower_no)]
    try:
        query_ids.append(int(borrower_no))
    except: pass
    
    result = collection.delete_one({"NO": {"$in": query_ids}})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Borrower not found")
        
    return {"status": "success", "message": "Borrower deleted"}
