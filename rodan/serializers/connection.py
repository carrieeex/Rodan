from rest_framework import serializers
from rodan.models.connection import Connection
from rodan.serializers.inputport import InputPortSerializer
from rodan.serializers.workflowjob import WorkflowJobSerializer
from rodan.serializers.outputport import OutputPortSerializer
from rodan.serializers.workflow import WorkflowSerializer


class ConnectionSerializer(serializers.HyperlinkedModelSerializer):
    uuid = serializers.Field(source='uuid')
    input_port = InputPortSerializer()
    output_port = OutputPortSerializer()
    input_workflow_job = WorkflowJobSerializer()
    output_workflow_job = WorkflowJobSerializer()
    workflow = WorkflowSerializer()

    class Meta:
        model = Connection
        fields = ("url",
                  "uuid",
                  "input_port",
                  "input_workflow_job",
                  "output_port",
                  "output_workflow_job",
                  "workflow")


class ConnectionListSerializer(serializers.HyperlinkedModelSerializer):
    uuid = serializers.Field(source='uuid')
    workflow = serializers.HyperlinkedRelatedField(view_name="workflow-detail")

    class Meta:
        model = Connection
        fields = ("url",
                  "uuid",
                  "input_port",
                  "input_workflow_job",
                  "output_port",
                  "output_workflow_job",
                  "workflow")