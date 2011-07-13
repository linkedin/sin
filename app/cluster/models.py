import logging
from django.db import models
from django.utils.translation import ugettext_lazy as _

from utils import enum
from utils.enum import to_choices

class Group(models.Model):
  name = models.CharField(max_length=20)

class Node(models.Model):
  host = models.CharField(max_length=40)
  agent_port = models.IntegerField()

  group = models.ForeignKey(Group, related_name="nodes", null=True)

