from sqlalchemy import String, JSON
from app.core.models import domain,col
requests=domain('image_requests',[col('title',String(250)),col('prompt'),col('status',String(30)),col('metadata',JSON)],[('requested_by','users'),('generation_job_id','generation_jobs',True)])
