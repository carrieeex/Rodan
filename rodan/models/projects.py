import os
import uuid
import shutil

from django.db import models
from django.contrib.auth.models import User
from django.conf import settings

import rodan.jobs
from rodan.models.jobs import JobType
from rodan.utils import get_size_in_mb

from PIL import Image
from cStringIO import StringIO

class RodanUser(models.Model):
    class Meta:
        app_label = 'rodan'

    user = models.OneToOneField(User)
    affiliation = models.CharField(max_length=100)

    def __unicode__(self):
        return self.user.username


class Project(models.Model):
    class Meta:
        app_label = 'rodan'

    name = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    creator = models.ForeignKey(RodanUser)
    pk_name = 'project_id'

    def __unicode__(self):
        return self.name

    @models.permalink
    def get_absolute_url(self):
        return ('rodan.views.projects.view', [str(self.id)])

    # Takes in a User (not a RodanUser), returns true if the user created it
    def is_owned_by(self, user):
        return user.is_authenticated() and self.creator == user.get_profile()

    def get_percent_done(self):
        percent_done = sum(page.get_percent_done() for page in self.page_set.all())
        return percent_done / self.page_set.count() if self.page_set.count() else 0

    def get_divaserve_dir(self):
        return os.path.join(settings.MEDIA_ROOT,
                            "%d" % self.id,
                            'final')

    def is_partially_complete(self):
        Job = models.loading.get_model('rodan', 'Job')
        diva_job = Job.objects.get(pk='diva-preprocess')
        return any(page.get_percent_done() == 100 and page.workflow.jobitem_set.filter(job=diva_job).count() for page in self.page_set.all())

    def clone_workflow_for_page(self, workflow, page, user):
        Workflow = models.loading.get_model('rodan', 'Workflow')
        new_wf = Workflow.objects.create(project=self, name=workflow.name, description=workflow.description, has_started=True)

        for jobitem in workflow.jobitem_set.all():
            new_wf.jobitem_set.create(sequence=jobitem.sequence, job=jobitem.job)

        page.workflow = new_wf
        page.save()

        return new_wf


class Job(models.Model):
    """
    The slug is automatically generated from the class definition, but
    can be overridden by setting the 'slug' attribute. This is used for URL
    routing purposes.

    The name is also automatically generated from the class definition, but,
    again, can be overridden, this time by setting the 'name' attribute. This
    is used for display purposes.

    The module is in the form 'rodan.jobs.binarisation.Binarise', where
    'binarisation.py' is a file under rodan/jobs, and Binarise is a class
    defined in that file.

    All instances of this model (i.e. rows in the database) are created after
    syncing the database (if they have not already been created), using the
    post_sync hook. They should not be added manually, via fixtures or
    otherwise.
    """
    class Meta:
        app_label = 'rodan'

    name = models.CharField(max_length=50)
    slug = models.CharField(max_length=20, primary_key=True)
    module = models.CharField(max_length=100)
    enabled = models.BooleanField(default=True)
    is_automatic = models.BooleanField()
    pk_name = 'job_slug'
    is_required = models.BooleanField()

    def __unicode__(self):
        return self.name

    @models.permalink
    def get_absolute_url(self):
        return ('rodan.views.jobs.view', [self.slug])

    def get_view(self, page):
        """
        Returns a tuple of the template to use and a context dictionary
        """
        return ('jobs/%s.html' % self.slug, self.get_object().get_context(page))

    def get_object(self):
        return rodan.jobs.jobs[self.module]

    def is_compatible(self, other_job):
        """
        Given another job, checks if it's compatible as the next job
        (based on input/output types)
        """
        return self.get_object().output_type == other_job.get_object().input_type

    def get_compatible_jobs(self):
        compatible_function = self.is_compatible
        return filter(compatible_function, Job.objects.all())


class Workflow(models.Model):
    class Meta:
        app_label = 'rodan'

    project = models.ForeignKey(Project)
    name = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    jobs = models.ManyToManyField(Job, through='JobItem', null=True, blank=True)
    has_started = models.BooleanField(default=False)
    pk_name = 'workflow_id'

    def __unicode__(self):
        return self.name

    @models.permalink
    def get_absolute_url(self):
        return ('rodan.views.workflows.view', [str(self.id)])

    def get_percent_done(self):
        percent_done = sum(page.get_percent_done() for page in self.page_set.all())
        return percent_done / self.page_set.count() if self.page_set.count() else 0

    def get_workflow_jobs(self):
        """Get all the the job items in a workflow."""
        return [job_item.job for job_item in self.jobitem_set.all()]

    def get_required_jobs(self):
        """
        Return a list of all the jobs with a required flag that are compatible with the last added job
        that can be added (i.e. are not already chosen).
        """
        workflow_jobs=self.get_workflow_jobs()
        if len(workflow_jobs):
            last_job = self.get_workflow_jobs()[-1]
            return [job for job in Job.objects.filter(is_required=True) if job not in self.get_workflow_jobs() and last_job.is_compatible(job)]
        else:
            return [job for job in Job.objects.filter(is_required=True) if job not in self.get_workflow_jobs() and job.get_object().input_type==JobType.IMAGE]

    def has_required_compatibility(self, job):
        """
        Check that the arguement job is compatible with all required jobs in this step. 
        i.e., has the same output type as all the input types of the required jobs at the current step.
        """ 
        return all(job.is_compatible(req_job) for req_job in self.get_required_jobs())

    def get_available_jobs(self):
        """
        Return a list of the available jobs to choose from when creating a workflow,
        checks that all required jobs are added before moving to a different input type.
        """
        available_jobs = []
        workflow_jobs = self.get_workflow_jobs()
        required_jobs = self.get_required_jobs()
        if len(workflow_jobs):
            last_job = workflow_jobs[-1]
            #First finds enabled jobs that aren't required
            available_jobs = [job for job in Job.objects.filter(enabled=True, is_required=False) if job not in workflow_jobs and last_job.is_compatible(job)]
            #If there are required jobs, filters out those jobs not compatible with required jobs, else returns available jobs
            if required_jobs:
                available_jobs = required_jobs + [job for job in available_jobs and self.has_required_compatibility(job)]
        else:
            #If there aren't any workflow jobs, finds all enabled jobs that aren't required            
            available_jobs = [job for job in Job.objects.filter(enabled=True, is_required=False) if job.get_object().input_type == JobType.IMAGE]
            #If there are required jobs, filters out all jobs that aren't compatible with the required jobs
            if required_jobs:
                available_jobs = required_jobs + [job for job in available_jobs if self.has_required_compatibility(job)]

        return available_jobs

    def get_removable_jobs(self):
        """
        Get all the removeable jobs in a workflow (i.e., jobs with the same input as output type).
        """
        return [job for job in self.get_workflow_jobs() if job.get_object().input_type == job.get_object().output_type]

    def get_jobs_same_io_type(self):
        """
        Get all the jobs in the available_jobs that have the same input_type as output_type.
        """
        return [job for job in self.get_available_jobs() if job.get_object().input_type == job.get_object().output_type]

    def get_jobs_diff_io_type(self):
        return [job for job in self.get_available_jobs() if job.get_object().input_type != job.get_object().output_type]

class Page(models.Model):
    class Meta:
        app_label = 'rodan'
        unique_together = ('project', 'sequence')
        ordering = ['project', 'sequence']

    project = models.ForeignKey(Project)
    # Will only begin processing once a workflow has been specified
    workflow = models.ForeignKey(Workflow, null=True, blank=True, on_delete=models.SET_NULL)
    filename = models.CharField(max_length=50)
    tag = models.CharField(max_length=50, null=True, blank=True, help_text="Optional tag for the page. Sort of like a nickname.")
    # Used in conjunction with the @rodan_view decorator
    pk_name = 'page_id'
    sequence = models.IntegerField(null=True)
    is_ready = models.BooleanField(default=False)
    original_width = models.IntegerField(null=True)
    original_height = models.IntegerField(null=True)
    latest_width = models.IntegerField(null=True)
    latest_height = models.IntegerField(null=True)

    # If the tag is defined, it returns that; otherwise, returns the filename
    def __unicode__(self):
        return self.tag or self.filename

    # Defines the hierarchy for generating breadcrumbs
    def get_parent(self):
        return self.project
    
    def get_previous_page(self):
        return sorted(self.project.page_set.all(), key=lambda page: page.sequence)[self.sequence - 2] if self.sequence > 1 else None

    @models.permalink
    def get_absolute_url(self):
        return ('rodan.views.pages.view', [str(self.id)])

    def get_original_image_size(self):
        """
        Gets the size of the TIFF image that was originally uploaded.
        """
        return get_size_in_mb(os.path.getsize(self.get_latest_file_path('original')))

    @staticmethod
    def _get_thumb_filename(path, size):
        base_path, _ = os.path.splitext(path)
        return "%s_%s.%s" % (base_path, size, settings.THUMBNAIL_EXT)

    def _get_thumb_path(self, size, job):
        return os.path.join("%d" % self.project.id,
                            "%d" % self.id,
                            "%s" % job.slug if job is not None else '',
                            self._get_thumb_filename(self.filename, size))

    def _get_latest_file_path(self, file_type):
        """
        Helper method used by both get_file_url and get_file_path.
        Does not include the MEDIA_ROOT or MEDIA_URL.
        For getting the path to a file associated with a page.

        If the `latest` keyword argument is set to True, it will return the
        most recently created file of the specified type. Otherwise,
        """
        # Importing ResultFile directly would result in circular imports
        file_manager = models.loading.get_model('rodan', 'ResultFile').objects

        """
        The query below selects all the result files that match the following criteria:

        * The page of the result is the current page
        * The workflow that the result's job item belongs to is this page's
        * The result's end_total_time field is not null (so, job is complete)
        * The file type is the desired type

        It is then ordered by result's job item's sequence in the workflow.
        This is so that we get the latest file of the type we want.
        """
        files = file_manager.filter(result__page=self,
                                    result__job_item__workflow=self.workflow,
                                    result__end_total_time__isnull=False,
                                    result_type=file_type) \
                                    .order_by('-result__job_item__sequence') \
                                    .all()

        try:
            return files[0].filename
        except IndexError:
            return None

    def get_mei_url(self):
        return settings.MEDIA_URL + self._get_latest_file_path('mei')

    def get_mei_path(self):
        return settings.MEDIA_ROOT + self._get_latest_file_path('mei')

    def get_latest_file_path(self, file_type):
        """
        Returns the absolute filepath to the latest result file creatd
        of the specified type. The `file_type` keyword argument is a string
        indicating the file extension (e.g. 'json', 'xml', 'tiff'). If no
        result files have been created of that type, then None will be
        returned.

        If the file_type is tiff and no jobs have been completed on this page,
        the original image file is returned (and so None will never be
        returned). It will also be returned if the file type is 'original'.
        """

        if file_type == 'page_number':
            # Needed for solr indexing. Really hacky, will fix eventually
            return self.sequence

        if file_type == 'project_id':
            # Same as above. Sorry.
            return self.project.id

        if file_type == 'prebin':
            if self.workflow.jobitem_set.count():
                for jobitem in self.workflow.jobitem_set.order_by('-sequence'):
                    if jobitem.job.get_object().output_type == JobType.IMAGE:
                        return self.get_job_path(jobitem.job, 'tiff')

        if file_type != 'original':
            latest_file_path = self._get_latest_file_path(file_type)

            if latest_file_path is not None:
                return os.path.join(settings.MEDIA_ROOT,
                                latest_file_path)

        if file_type == 'original' or file_type == 'prebin' or file_type == 'tiff':
            return os.path.join(settings.MEDIA_ROOT,
                                "%d" % self.project_id,
                                "%d" % self.id,
                                self.filename)

    def get_latest_thumb_url(self, size=settings.SMALL_THUMBNAIL):
        latest_file_path = self._get_latest_file_path('tiff')

        if latest_file_path is not None:
            file_path = self._get_thumb_filename(latest_file_path, size)
            # This is not actually a filepath but there are / issues otherwise
            return os.path.join(settings.MEDIA_URL,
                                file_path)
        else:
            return self.get_thumb_url(size, None)

    def get_latest_thumb_path(self, size=settings.SMALL_THUMBNAIL):
        latest_file_path = self._get_latest_file_path('tiff')

        if latest_file_path is not None:
            file_path = self._get_thumb_filename(latest_file_path, size)
            # This is not actually a filepath but there are / issues otherwise
            return os.path.join(settings.MEDIA_ROOT,
                                file_path)
        else:
            return self.get_thumb_path(size, None)

    def get_pre_bin_image_url(self, size=settings.LARGE_THUMBNAIL):
        """
        Get the url to the latest pre-binarised image (i.e. the output of the
        step right before binarisation, or the latest step if binarisation is
        either not part of the workflow or has not yet been completed.
        """
        original = self.get_thumb_url(size=size)
        if self.workflow.jobitem_set.count():
            for jobitem in self.workflow.jobitem_set.order_by('-sequence'):
                if jobitem.job.get_object().output_type == JobType.IMAGE:
                    return self.get_thumb_url(size=size, job=jobitem.job)

        # Otherwise, just return the original
        return original

    def get_current_preview_image(self, size=settings.MEDIUM_THUMBNAIL):
        """
        Get the url to the latest workflow preview image for when you're adding
        jobs to the workflow
        """
        original = self.get_thumb_url(size=size)
        if self.workflow.jobitem_set.count():
            for jobitem in self.workflow.jobitem_set.order_by('-sequence'):
                if jobitem.job.get_object().output_type == JobType.IMAGE or jobitem.job.get_object().output_type == JobType.BINARISED_IMAGE:
                    return self.get_thumb_url(size=size, job=jobitem.job)

        # Otherwise, just return the original
        return original

    def get_thumb_url(self, size=settings.SMALL_THUMBNAIL, job=None, cache=True):
        url = os.path.join(settings.MEDIA_URL,
                            self._get_thumb_path(size, job))

        if cache:
            return url
        else:
            return url + '?_=' + str(uuid.uuid4())[:8]

    def get_thumb_path(self, size=settings.SMALL_THUMBNAIL, job=None):
        """
        Get the absolute path to the thumbnail image.

        `size` is the width, in pixels, of the desired thumbnail image.
        `job` is the job object (either of type JobBase or a model).

        If you want to get the thumbnail for the latest job, use
        get_latest_image_path() and pass in the desired size as a keyword
        argument.
        """
        return os.path.join(settings.MEDIA_ROOT,
                            self._get_thumb_path(size=size, job=job))

    def _get_job_path(self, job, ext):
        """
        Returns the relative path to the file for the specified
        job and extension.
        """
        basename, _ = os.path.splitext(self.filename)

        return os.path.join("%d" % self.project.id,
                            "%d" % self.id,
                            "%s" % job.slug,
                            "%s.%s" % (basename, ext))

    def get_job_path(self, job, ext):
        """
        Returns the absolute path to the file for the specified
        job and extension. Used when saving files (only).

        Job will never be None. To save original image thumbnails, use
        get_thumb_path.
        """
        basename, _ = os.path.splitext(self.filename)

        return os.path.join(settings.MEDIA_ROOT,
                            "%d" % self.project.id,
                            "%d" % self.id,
                            "%s" % job.slug,
                            "%s.%s" % (basename, ext))

    def get_pyramidal_tiff_path(self):
        """
        Because divaserve expects all the pyramidal tiff images for one
        project to be stored in the same directory.
        """
        return os.path.join(self.project.get_divaserve_dir(),
                            "%d.tiff" % self.sequence)

    def get_next_job_item(self, user=None):
        if not self.workflow:
            return None

        for job_item in self.workflow.jobitem_set.all():
            page_results = job_item.result_set.filter(page=self)
            no_result = page_results.count() == 0
            if no_result:
                return job_item
            else:
                first_result = page_results.all()[0]  # this bombs sometimes
                manual_not_done = first_result.end_manual_time is None
                automatic_not_done = first_result.end_total_time is None
                if manual_not_done and first_result.user == user:
                    return job_item
                elif automatic_not_done:
                    # This job is still processing - return None
                    return None

    def get_next_job(self, user=None):
        """
        If user is None, it returns the next available job that has not yet
        been started. If the user is specified, it returns the next
        available job that has either not been started or that has been
        started by the specified user.
        """
        next_job_item = self.get_next_job_item(user=user)
        return next_job_item.job if next_job_item is not None else None

    def start_next_job(self, user):
        next_job_item = self.get_next_job_item(user=user)
        # Create a new result only if there are none
        if next_job_item is not None and next_job_item.result_set.filter(page=self).count() == 0:
            Result = models.loading.get_model('rodan', 'Result')
            result = Result.objects.create(job_item=next_job_item, user=user, page=self)
            return result

    def start_next_automatic_job(self, user):
        next_job = self.get_next_job(user=user)
        if next_job is not None:
            next_job_obj = next_job.get_object()
            if next_job_obj.is_automatic:
                if next_job.get_object().all_pages:
                    # the following statement gets all the pages that have not completed the multi-page job
                    # and that are part of the same workflow (i.e. if there is a page that uses the same wf
                    # as this page but has completed the given multi-page job, it will be ignored)
                    target_workflow_pages = [page for page in self.workflow.page_set.all() \
                                                if not page.is_job_complete(next_job.jobitem_set.filter(workflow=page.workflow))]
                    # print target_workflow_pages

                    # for page in target_workflow_pages:
                    #     if page.is_job_complete(next_job.jobitem_set.all()):
                    #         page.reset_to_job(next_job)

                    project_pages_readiness = True
                    for page in target_workflow_pages:
                        if page.get_next_job(user=user).slug != next_job.slug:
                            project_pages_readiness = False
                            break

                    if project_pages_readiness:
                        result_ids = []
                        for pg in target_workflow_pages:
                            res = pg.start_next_job(user)
                            res.update_end_manual_time()
                            result_ids.append(res.id)

                        next_job_obj.on_post(result_ids, **next_job_obj.parameters)
                else:
                    next_result = self.start_next_job(user)
                    next_result.update_end_manual_time()
                    next_job_obj.on_post(next_result.id, **next_job_obj.parameters)

    def get_percent_done(self):
        Result = models.loading.get_model('rodan', 'Result')
        num_complete = Result.objects.filter(page=self, end_total_time__isnull=False).count()
        try:
            num_jobs = self.workflow.jobitem_set.count()
            return (100 * num_complete) / num_jobs
        except (AttributeError, ZeroDivisionError):
            return 0

    def handle_image_upload(self, file):
        # Might need to fix the filename extension
        basename, extension = os.path.splitext(self.filename)
        self.filename = basename + '.tiff'
        self.save()

        image_path = self.get_latest_file_path('tiff')
        rodan.jobs.utils.create_dirs(image_path)

        # perform image conversion, if necessary
        output_file = open(image_path, 'wb+')
        if extension != '.tiff':
            uploaded_buffer = StringIO(file.read())
            uploaded_image = Image.open(uploaded_buffer)
            uploaded_image.save(output_file, 'TIFF')
            uploaded_buffer.close()
            output_file.close()
        else:
            with output_file as destination:
                for chunk in file.chunks():
                    destination.write(chunk)

        # Now generate thumbnails
        rodan.jobs.thumbnail.create_thumbnails.delay(self.id, image_path, settings.THUMBNAIL_SIZES)

    def is_job_complete(self, job_item):
        Result = models.loading.get_model('rodan', 'Result')
        return Result.objects.filter(job_item=job_item,
                                     page=self,
                                     end_total_time__isnull=False
                                     ).count()

    def reset_to_job(self, job):
        this_sequence = self.workflow.jobitem_set.get(job=job).sequence
        # Delete all the results whose jobitems have sequence >= this one
        results_to_delete = self.result_set.filter(job_item__sequence__gte=this_sequence)
        for result in results_to_delete:
            path_to_job_file_results = os.path.join(settings.MEDIA_ROOT,
                            "%d" % self.project.id,
                            "%d" % self.id,
                            "%s" % result.job_item.job.slug)
            if os.path.exists(path_to_job_file_results):
                shutil.rmtree(path_to_job_file_results)
        results_to_delete.delete()


class JobItem(models.Model):
    class Meta:
        app_label = 'rodan'
        unique_together = ('workflow', 'sequence')
        ordering = ['sequence']

    workflow = models.ForeignKey(Workflow)
    job = models.ForeignKey(Job)
    sequence = models.IntegerField()

    def __unicode__(self):
        return "%s in workflow '%s' (step %d)" % (self.job, self.workflow, self.sequence)


class ActionParam(models.Model):
    """
    Specifies the intended defaults for a job.
    """
    class Meta:
        app_label = 'rodan'
        unique_together = ('job_item', 'key')

    job_item = models.ForeignKey(JobItem)
    key = models.CharField(max_length=50)
    value = models.CharField(max_length=50)

    def __unicode__(self):
        return "%s: %s, for %s" % (self.key, self.value, self.job_item)


# Defines a post_save hook to ensure that a RodanUser is created for each User
def create_rodan_user(sender, instance, created, **kwargs):
    if created:
        RodanUser.objects.create(user=instance)

models.signals.post_save.connect(create_rodan_user, sender=User)


# Defines a post-delete hook on Page to ensure that the image files are deleted
def delete_page_files(sender, instance, **kwargs):
    # Delete the entire directory
    directory = os.path.dirname(instance.get_latest_file_path('tiff'))
    shutil.rmtree(directory)

    # If the project directory is empty, delete that as well
    parent_dir = os.path.dirname(directory)
    try:
        os.rmdir(parent_dir)
    except OSError:
        pass

models.signals.post_delete.connect(delete_page_files, sender=Page)
