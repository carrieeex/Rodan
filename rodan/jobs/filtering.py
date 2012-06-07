import gamera.core

from celery.task import task

import utility
from rodan.models.jobs import JobType, JobBase
from rodan.models import Result

@task(name="filters.rank")
def rank_filter(result_id, **kwargs):
    """
      *rank_val* (1, 2, ..., *k* * *k*)
        The rank of the windows pixels to select for the center. (k*k+1)/2 is
        equivalent to the median.

      *k* (3, 5 ,7, ...)
        The window size (must be odd).

      *border_treatment* (0, 1)
        When 0 ('padwhite'), window pixels outside the image are set to white.
        When 1 ('reflect'), reflecting boundary conditions are used.
    """
    gamera.core.init_gamera()

    result = Result.objects.get(pk=result_id)
    page_file_name = result.page.get_latest_file(JobType.IMAGE) 

    output_img = gamera.core.load_image(page_file_name).rank(kwargs['rank_val'],kwargs['k'],kwargs['border_treatment'])

    full_output_path = result.page.get_filename_for_job(result.job_item.job)
    utility.create_result_output_dirs(full_output_path)

    gamera.core.save_image(output_img, full_output_path)

    result.save_parameters(**kwargs)
    result.create_file(output_file_name, JobType.IMAGE_ONEBIT) #need to specify output type in this case its the same as input but we cannot send JobType.IMAGE --> tuple
    result.total_timestamp()

class RankFilter(JobBase):
    name = 'Rank filter'
    slug = 'rank-filter'
    input_type = JobType.IMAGE_GREY
    output_type = input_type
    description = 'Applies rank filter on a binarized image'
    show_during_wf_create = True
    arguments = {
        'rank_val': 9,
        'k': 9,
        'border_treatment':0
    }
    task = rank_filter