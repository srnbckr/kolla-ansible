#!/usr/bin/env python

# Copyright 2015 Sam Yaple
# Copyright 2016 intel
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import shutil
import tempfile

from yaml import dump
from yaml import safe_load
try:
    from yaml import CDumper as Dumper  # noqa: F401
    from yaml import CLoader as Loader  # noqa: F401
except ImportError:
    from yaml import Dumper  # noqa: F401
    from yaml import Loader  # noqa: F401


from ansible import constants
from ansible.plugins import action
import six

DOCUMENTATION = '''
---
module: merge_yaml
short_description: Merge yaml-style configs
description:
     - PyYAML is used to merge several yaml files into one
options:
  dest:
    description:
      - The destination file name
    required: True
    type: str
  sources:
    description:
      - A list of files on the destination node to merge together
    default: None
    required: True
    type: str
author: Sean Mooney
'''

EXAMPLES = '''
Merge multiple yaml files:

- hosts: localhost
  tasks:
    - name: Merge yaml files
      merge_yaml:
        sources:
          - "/tmp/default.yml"
          - "/tmp/override.yml"
        dest:
          - "/tmp/out.yml"
'''


class ActionModule(action.ActionBase):

    TRANSFERS_FILES = True

    def read_config(self, source):
        result = None
        # Only use config if present
        if os.access(source, os.R_OK):
            with open(source, 'r') as f:
                template_data = f.read()

            # set search path to mimic 'template' module behavior
            searchpath = [
                self._loader._basedir,
                os.path.join(self._loader._basedir, 'templates'),
                os.path.dirname(source),
            ]
            self._templar.environment.loader.searchpath = searchpath

            template_data = self._templar.template(template_data)
            result = safe_load(template_data)
        return result or {}

    def run(self, tmp=None, task_vars=None):
        if task_vars is None:
            task_vars = dict()
        result = super(ActionModule, self).run(tmp, task_vars)
        del tmp  # not used

        # save template args.
        extra_vars = self._task.args.get('vars', list())
        old_vars = self._templar._available_variables

        temp_vars = task_vars.copy()
        temp_vars.update(extra_vars)
        self._templar.set_available_variables(temp_vars)

        output = {}
        sources = self._task.args.get('sources', None)
        if not isinstance(sources, list):
            sources = [sources]
        for source in sources:
            Utils.update_nested_conf(output, self.read_config(source))

        # restore original vars
        self._templar.set_available_variables(old_vars)

        local_tempdir = tempfile.mkdtemp(dir=constants.DEFAULT_LOCAL_TMP)

        try:
            result_file = os.path.join(local_tempdir, 'source')
            with open(result_file, 'w') as f:
                f.write(dump(output, default_flow_style=False))

            new_task = self._task.copy()
            new_task.args.pop('sources', None)

            new_task.args.update(
                dict(
                    src=result_file
                )
            )

            copy_action = self._shared_loader_obj.action_loader.get(
                'copy',
                task=new_task,
                connection=self._connection,
                play_context=self._play_context,
                loader=self._loader,
                templar=self._templar,
                shared_loader_obj=self._shared_loader_obj)
            result.update(copy_action.run(task_vars=task_vars))
        finally:
            shutil.rmtree(local_tempdir)
        return result


class Utils(object):
    @staticmethod
    def update_nested_conf(conf, update):
        for k, v in six.iteritems(update):
            if isinstance(v, dict):
                conf[k] = Utils.update_nested_conf(conf.get(k, {}), v)
            else:
                conf[k] = v
        return conf
