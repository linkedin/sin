import random, os, subprocess, socket
from django.conf import settings
from django.http import HttpResponse
from django.template import loader
from django.http import Http404

import kafka

from content_store.models import ContentStore
from cluster.models import Group, Node

from utils import enum, json

from django.utils import simplejson
import shutil
import urllib, urllib2

kafkaHost = settings.KAFKA_HOST
kafkaPort = int(settings.KAFKA_PORT)
kafkaProducer = kafka.KafkaProducer(kafkaHost, kafkaPort)

def storeExists(request,store_name):
  resp = {
    'exists' : ContentStore.objects.filter(name=store_name).exists()
  }
  return HttpResponse(json.json_encode(resp))

def openStore(request,store_name):
  store = ContentStore.objects.get(name=store_name)
  if not store:
    resp = {
      'ok' : False,
      'error' : 'store: %s does not exist.' % store_name
    }
    return HttpResponse(json.json_encode(resp))

  resp = {
    'ok' : True,
    'id': store.id,
    'name': store.name,
    'sensei_port': store.sensei_port,
    'broker_host': store.broker_host,
    'broker_port': store.broker_port,
    'config': store.config,
    'created': store.created,
    'status': store.status,
    'status_display': unicode(enum.STORE_STATUS_DISPLAY[store.status]),
    'kafkaHost' : kafkaHost,
    'kafkaPort' : kafkaPort,
    'description' : store.description,
  }
  return HttpResponse(json.json_encode(resp))

def newStore(request,store_name):
  if ContentStore.objects.filter(name=store_name).exists():
    resp = {
      'ok' : False,
      'error' : 'store: %s already exists.' % store_name
    }
    return HttpResponse(json.json_encode(resp))

  desc = request.POST.get('desc')

  # Check for nodes:
  if Node.objects.count() == 0:
    n = Node.objects.create(host=socket.gethostbyaddr(socket.gethostname())[0], group=Group(pk=1))

  store = ContentStore(name=store_name,
    description=desc)
  store.save()
  resp = {
    'ok' : True,
    'id': store.id,
    'name': store.name,
    'sensei_port': store.sensei_port,
    'broker_host': store.broker_host,
    'broker_port': store.broker_port,
    'config': store.config,
    'created': store.created,
    'status': store.status,
    'status_display': unicode(enum.STORE_STATUS_DISPLAY[store.status]),
    'kafkaHost' : kafkaHost,
    'kafkaPort' : kafkaPort,
    'description' : store.description,
  }
  return HttpResponse(json.json_encode(resp))

def deleteStore(request,store_name):
  if not ContentStore.objects.filter(name=store_name).exists():
    resp = {
      'ok' : False,
      'msg' : 'store: %s does not exist.' % store_name
    }
    return HttpResponse(json.json_encode(resp))
  stopStore(request, store_name)

  store_data_dir = os.path.join(settings.STORE_HOME, store_name)
  try:
    shutil.rmtree(store_data_dir)
  except:
    pass
  ContentStore.objects.filter(name=store_name).delete()
  resp = {
    'ok' : True,
    'msg' : 'store: %s successfully deleted.' % store_name
  }
  return HttpResponse(json.json_encode(resp))

def updateConfig(request, store_name):
  config = request.POST.get('config');
  resp = {
    'ok': False,
  }
  if config:
    # TODO: valid configuration.
    ContentStore.objects.filter(name=store_name).update(config=config);
    resp['ok'] = True
  else:
    resp['error'] = 'No config provided.'

  return HttpResponse(json.json_encode(resp))

def addDoc(request,store_name):
  doc = request.POST.get('doc');
  
  if not doc:
    resp = {'ok':False,'error':'no doc posted'}
  else:
    try:
      jsonDoc = simplejson.loads(doc.encode('utf-8'))
      kafkaProducer.send([json.json_encode(jsonDoc)], store_name.encode('utf-8'))
      resp = {'ok': True,'numPosted':1}
    except ValueError:
      resp = {'ok':False,'error':'invalid json: %s' % doc}
    except Exception as e:
      resp = {'ok':False,'error':e}
  
  return HttpResponse(json.json_encode(resp))
  

def addDocs(request,store_name):
  docs = request.POST.get('docs');  
  if not docs:
    resp = {'ok':False,'error':'no docs posted'}
  else:
    try:
      jsonArray = simplejson.loads(docs.encode('utf-8'))
      messages = []
      for obj in jsonArray:
        str = json.json_encode(obj).encode('utf-8')
        messages.append(str)
      kafkaProducer.send(messages, store_name.encode('utf-8'))
      resp = {'ok':True,'numPosted':len(messages)}
    except ValueError:
      resp = {'ok':False,'error':'invalid json: %s' % docs}
    except Exception as e:
      resp = {'ok':False,'error':e}
  return HttpResponse(json.json_encode(resp))

def startStore(request, store_name):
  try:
    store = ContentStore.objects.get(name=store_name)
    webapp = os.path.join(settings.SENSEI_HOME,'src/main/webapp')
    store_home = os.path.join(settings.STORE_HOME, store_name)
    index = os.path.join(store_home, 'index')

    sensei_properties = loader.render_to_string(
      'sensei-conf/sensei.properties', {
        'store': store,
        'index': index,
        'webapp': webapp,
        })
    sensei_custom_facets = loader.render_to_string(
      'sensei-conf/custom-facets.xml', {
        })
    sensei_plugins = loader.render_to_string(
      'sensei-conf/plugins.xml', {
        })

    params = {}
    params["name"] = store_name
    params["sensei_port"] = store.sensei_port
    params["broker_host"] = store.broker_host
    params["broker_port"] = store.broker_port
    params["sensei_properties"] = sensei_properties
    params["sensei_custom_facets"] = sensei_custom_facets
    params["sensei_plugins"] = sensei_plugins
    params["schema"] = store.config
  
    nodes = store.group.nodes.all()
    for node in nodes:
      output = urllib2.urlopen("http://%s:%d/%s" % (node.host, node.agent_port, "start-store"),
                               urllib.urlencode(params))
    store.status = enum.STORE_STATUS['running']
    store.save()
    return HttpResponse(json.json_encode({
      "ok":True,
      "status": store.status,
      "status_display": unicode(enum.STORE_STATUS_DISPLAY[store.status]),
    }))
  except Exception as e:
    return HttpResponse(json.json_encode({'ok':False,'error':e}))

def stopStore(request, store_name):
  try:
    store = ContentStore.objects.get(name=store_name)

    params = {}
    params["name"] = store_name

    nodes = store.group.nodes.all()
    for node in nodes:
      output = urllib2.urlopen("http://%s:%d/%s" % (node.host, node.agent_port, "stop-store"),
                               urllib.urlencode(params))
    store.status = enum.STORE_STATUS['stopped']
    store.save()
    return HttpResponse(json.json_encode({
      "ok":True,
      "status": store.status,
      "status_display": unicode(enum.STORE_STATUS_DISPLAY[store.status]),
    }))
  except Exception as e:
    return HttpResponse(json.json_encode({'ok':False,'error':e}))
  

def restartStore(request, store_name):
  stopStore(request, store_name)
  return startStore(request, store_name)

def getSize(request,store_name):
  resp = {'store':store_name,"size":0}
  return HttpResponse(json.json_encode(resp))
  
def getDoc(request,store_name,id):
  uid = long(id)
  doc = {'id':uid}
  resp = {'store':store_name,'doc':doc}
  return HttpResponse(json.json_encode(resp))

def available(request,store_name):
  if ContentStore.objects.filter(name=store_name).exists():
    resp = {'ok':True,'store':store_name,"available":True}
  else:
    resp = {'ok':False,'error':'store: %s does not exist.' % store_name}
  return HttpResponse(json.json_encode(resp))

def stores(request):
  objs = ContentStore.objects.order_by('-created')
  resp = [{
      'id': store.id,
      'name': store.name,
      'sensei_port': store.sensei_port,
      'broker_host': store.broker_host,
      'broker_port': store.broker_port,
      'config': store.config,
      'created': store.created,
      'description' : store.description,
      'status': store.status,
      'status_display': unicode(enum.STORE_STATUS_DISPLAY[store.status]),
    }
    for store in objs]
  return HttpResponse(json.json_encode(resp))

