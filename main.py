'''
Copyright (c) 2020 Cisco and/or its affiliates.

This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at

               https://developer.cisco.com/docs/licenses

All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.
'''

import logging
import socketserver
import requests
import ansible_runner, yaml
import time

# global vars
LOG_FILE = 'app.log'
HOST, PORT = "0.0.0.0", 514

# get credentials
config = yaml.safe_load(open("credentials.yml"))
ISE_username = config['ISE_username']
ISE_password = config['ISE_password']

# configure logging settings
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='', filename=LOG_FILE, filemode='a')

# Syslog Server class
class SyslogUDPHandler(socketserver.BaseRequestHandler):

	def handle(self):
		# get syslog message data
		data = bytes.decode(self.request[0].strip())
		socket = self.request[1]
		search_data = str(data)

		# filter for syslog with new SGACL creation
		search_string1 = '52000 NOTICE Configuration-Changes: Added configuration'
		search_string2 = 'AdminInterface=ERS'
		search_string3 = 'mediaType=vnd.com.cisco.ise.trustsec.sgacl.1.0+xml'
		if search_string1 in search_data:
			if search_string2 in search_data:
				if search_string3 in search_data:

					# get ISE and SGACL information
					ISE_instance = self.client_address[0]
					find_bulkId = 'bulkId='
					s = search_data.partition(find_bulkId)[2]
					bulkId = s.split('\\', 1)[0]

					# get SGACL content
					base_url = 'https://' + ISE_instance + ':9060/ers/config/sgacl/'
					headers = {
						'Accept': 'application/json'
					}
					while True:
						get_SGACL_ID = requests.get(base_url + 'bulk/' + bulkId, headers=headers, auth=(ISE_username, ISE_password), verify=False)
						SearchResult = get_SGACL_ID.json()
						SGACL_bulk = SearchResult['BulkStatus']['resourcesStatus'][0]
						SGACL_status = SGACL_bulk['status']
						if SGACL_status == 'SUCCESS':
							SGACL_ID = SGACL_bulk['id']
							SGACL_name = SGACL_bulk['name']
							break
						else:
							time.sleep(2)

					logging.info("SGACL named " + SGACL_name + " added on ISE instance " + ISE_instance) # add logging statement

					get_SGACL_content = requests.get(base_url + SGACL_ID, headers=headers, auth=(ISE_username, ISE_password), verify = False)
					get_SGACL_content_result = get_SGACL_content.json()['Sgacl']
					# SGACL_ipversion = get_SGACL_content_result['ipVersion']
					SGACL_content = get_SGACL_content_result['aclcontent']
					SGACL_content_list = SGACL_content.split('\n')

					logging.info("SGACL " + SGACL_name + " content: " + str(SGACL_content_list))  # add logging statement

					# use SGACL information to prepare Ansible playbook
					acl_in_playbook = []
					for ACE in SGACL_content_list:
						ace = 'access-list ' + SGACL_name + ' ' + ACE
						acl_in_playbook.append(ace)

					with open('env/extravars') as f:
						doc = yaml.load(f, Loader=yaml.FullLoader)
					doc['acl_name'] = SGACL_name
					doc['acl_entries'] = acl_in_playbook
					with open('env/extravars', 'w') as f:
						yaml.safe_dump(doc, f)

					# run Ansible playbook to apply ACL to ASA
					r = ansible_runner.run(private_data_dir='.', playbook='asa_acl.yml')

					logging.info("Ansible playbook run on ASA with following results: " + str(r.stats)) # add logging statement


if __name__ == "__main__":
	# start the UDP Server
	try:
		server = socketserver.UDPServer((HOST,PORT), SyslogUDPHandler)
		server.serve_forever(poll_interval=0.5)
	except (IOError, SystemExit):
		raise
	except KeyboardInterrupt:
		print ("Crtl+C Pressed. Shutting down.")