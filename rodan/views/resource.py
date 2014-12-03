import mimetypes
from celery import registry
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework import generics
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.core.urlresolvers import Resolver404
from rodan.helpers.object_resolving import resolve_to_object
from rodan.models import Project, Output, Resource, ResourceType
from rodan.serializers.resourcetype import ResourceTypeSerializer
from rodan.serializers.resource import ResourceSerializer
from rodan.jobs.helpers import ensure_compatible, create_thumbnails
from django.db.models import Q
from rodan.constants import task_status


class ResourceList(generics.ListCreateAPIView):
    """
    Returns a list of Resources. Accepts a POST request with a data body with
    multiple files to create new Resource objects. It will return the newly
    created Resource objects.

    #### Parameters
    - `project` -- GET & POST. UUID of a Project.
    - `result_of_workflow_run` -- GET-only. UUID of a WorkflowRun. Filters the results
      of a WorkflowRun.
    - `type` -- (optional) POST-only. User can claim the type of the files using
       this parameter to help Rodan convert it into compatible format. It could be:
        - An arbitrary MIME-type string.
        - Or a hyperlink to a ResourceType object.
    - `files` -- POST-only. The files.
    """
    model = Resource
    permission_classes = (permissions.IsAuthenticated, )
    serializer_class = ResourceSerializer
    filter_fields = ('project', )

    def get_queryset(self):
        # [TODO] filter according to the user?
        # initial queryset (before filtering on `filter_fields`)
        queryset = Resource.objects.all()
        wfrun_uuid = self.request.QUERY_PARAMS.get('result_of_workflow_run', None)
        if wfrun_uuid:
            queryset = queryset.filter(Q(origin__run_job__workflow_run__uuid=wfrun_uuid) &
                                       (Q(inputs__isnull=True) | ~Q(inputs__run_job__workflow_run__uuid=wfrun_uuid)))
        return queryset

    def post(self, request, *args, **kwargs):
        if not request.data.get('files', None):
            raise ValidationError({'files': ["You must supply at least one file to upload."]})
        claimed_mimetype = request.data.get('type', None)
        if claimed_mimetype:
            try:
                # try to see if user provide a url to ResourceType
                restype_obj = resolve_to_object(claimed_mimetype, ResourceType)
                claimed_mimetype = restype_obj.mimetype
            except (Resolver404, ResourceType.DoesNotExist):
                pass

        initial_data = {
            'resource_type': ResourceTypeSerializer(ResourceType.cached('application/octet-stream'), context={'request': request}).data['url'],
            'processing_status': task_status.SCHEDULED
        }
        if 'project' in request.data:
            initial_data['project'] = request.data['project']

        new_resources = []
        for fileobj in request.data.getlist('files'):
            serializer = ResourceSerializer(data=initial_data)
            serializer.is_valid(raise_exception=True)

            resource_obj = serializer.save(name=fileobj.name, creator=request.user)
            resource_obj.resource_file.save(fileobj.name, fileobj)  # arbitrarily provide one as Django will figure out the path according to upload_to

            resource_id = str(resource_obj.uuid)
            mimetype = claimed_mimetype or mimetypes.guess_type(fileobj.name, strict=False)[0]
            (registry.tasks[ensure_compatible.name].si(resource_id, mimetype) | create_thumbnails.si(resource_id)).apply_async()

            d = ResourceSerializer(resource_obj, context={'request': request}).data
            new_resources.append(d)

        return Response(new_resources, status=status.HTTP_201_CREATED)


class ResourceDetail(generics.RetrieveUpdateDestroyAPIView):
    """
    Perform operations on a single Resource instance.
    """
    model = Resource
    serializer_class = ResourceSerializer
    permission_classes = (permissions.IsAuthenticated, )
    queryset = Resource.objects.all() # [TODO] filter according to the user?
