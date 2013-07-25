import os
import tempfile
import shutil
import warnings
from celery import task
from django.core.files import File
import PIL.Image
import PIL.ImageFile
from rodan.helpers.dbmanagement import exists_in_db, refetch_from_db


@task(name="rodan.helpers.convert.ensure_compatible", ignore_result=True)
def ensure_compatible(page_object):
    page_object = refetch_from_db(page_object)

    filename = "compat_image.png"

    image = PIL.Image.open(page_object.page_image.path).convert('RGB')
    tmpdir = tempfile.mkdtemp()
    image.save(os.path.join(tmpdir, filename))

    compatible_image_path = os.path.join(page_object.image_path, filename)
    f = open(os.path.join(tmpdir, filename), 'rb')

    if exists_in_db(page_object):
        page_object.compat_page_image.save(compatible_image_path, File(f))
    else:
        warnings.warn("The page was deleted from the database before it could be processed.")

    f.close()
    shutil.rmtree(tmpdir)

    return page_object
