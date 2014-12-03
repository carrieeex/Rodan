from celery import registry, task, chord
from rodan.models import RunJob, Resource, WorkflowRun
from rodan.constants import task_status
from django.db.models import Q

# Read more on Django queries: https://docs.djangoproject.com/en/dev/topics/db/queries/

@task(name='rodan.core.master_task')
def master_task(workflow_run_id):
    # code here are run asynchronously. Any write to database should use `queryset.update()` method, instead of `obj.save()`.

    # set interactive runjobs ready for input
    RunJob.objects.filter(
        Q(workflow_run__uuid=workflow_run_id)
        & Q(status=task_status.SCHEDULED)
        & Q(workflow_job__job__interactive=True)
        & Q(ready_for_input=False)
        & (~Q(inputs__resource__compat_resource_file__exact='')   # no ANY input with compat_resource_file==''
           | Q(inputs__isnull=True))      # OR no input
    ).update(ready_for_input=True)


    # find runable runjobs
    runable_runjobs_query = RunJob.objects.filter(
        Q(workflow_run__uuid=workflow_run_id)
        & Q(status=task_status.SCHEDULED)
        & Q(workflow_job__job__interactive=False)
        & (~Q(inputs__resource__compat_resource_file__exact='')   # no ANY input with compat_resource_file==''
           | Q(inputs__isnull=True))      # OR no input
    )
    runable_runjobs_repeated = runable_runjobs_query.values('uuid', 'workflow_job__job__job_name')  # CAUTION: underlying database performs an INNER JOIN operation, which could return repeated lines due to reverse foreign key query "inputs".
    runable_runjobs = []
    uuid_set = set()
    for rj_value in runable_runjobs_repeated:
        if rj_value['uuid'] not in uuid_set:
            runable_runjobs.append(rj_value)
            uuid_set.add(rj_value['uuid'])

    if len(runable_runjobs) == 0:
        if not RunJob.objects.filter(Q(workflow_run__uuid=workflow_run_id) & ~Q(status=task_status.FINISHED)).exists():
            # WorkflowRun has finished!
            WorkflowRun.objects.filter(uuid=workflow_run_id).update(status=task_status.FINISHED)
        return False
    else:
        task_group = []
        runable_runjobs_query.update(status=task_status.PROCESSING)  # in test, tasks are executed synchronously, therefore update the status before dispatching the task
        for rj_value in runable_runjobs:
            task = registry.tasks[str(rj_value['workflow_job__job__job_name'])]
            runjob_id = str(rj_value['uuid'])
            task_group.append(task.si(runjob_id))

        async_task = chord(task_group)(master_task.si(workflow_run_id))
        runable_runjobs_query.update(celery_task_id=async_task.task_id)
        return True
