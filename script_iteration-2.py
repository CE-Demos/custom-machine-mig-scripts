import googleapiclient.discovery
import time
import os
from datetime import datetime

# --- ✅ Configuration: SET YOUR MIGRATION FILTERS AND PROJECT DETAILS ---

# The script will automatically find all VMs with this label.
# In GCP, add a label with key 'migrate' and value 'true' to your source VMs.
MIGRATION_LABEL_FILTER = "labels.migrate=true"

# --- Global Project Details ---
SOURCE_PROJECT_ID = "ce-ai-chatbot"
SOURCE_ZONE = "us-central1-c"  # e.g., "us-central1-a"
DESTINATION_PROJECT_ID = "ce-testing-465204"
DESTINATION_PROJECT_NUMBER="526827734705"
NETWORK_NAME = "new-base-network"
SUBNET_NAME = "new-first-subnet"
DESTINATION_ZONE = "us-central1-a"

# --- Helper Functions ---

def wait_for_operation(compute, project, operation):
    """
    Waits for a GCP Compute Engine operation to complete.
    Handles both global and zonal operations automatically.
    """
    print(f"⏳ Waiting for operation '{operation['name']}'...")

    while True:
        if 'zone' in operation:
            result = compute.zoneOperations().get(
                project=project,
                zone=os.path.basename(operation['zone']),
                operation=operation['name']
            ).execute()
        else:
            result = compute.globalOperations().get(
                project=project,
                operation=operation['name']
            ).execute()

        if result['status'] == 'DONE':
            print("✅ Operation finished.")
            if 'error' in result:
                print("❌ Operation failed!")
                raise Exception(result['error'])
            return result
        
        time.sleep(3)

# --- Migration Logic for a Single VM ---

def migrate_vm(compute, vm_config):
    """Orchestrates the migration for a single VM."""
    migration_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    source_vm = vm_config['source_vm_name']
    source_zone = vm_config['source_zone']
    new_vm = vm_config['new_vm_name']
    machine_type = vm_config['machine_type']
    
    print(f"\n🚀 Starting migration for VM '{source_vm}' with Migration ID: {migration_id}")
    print("================================================================")

    # Step 1: Stop the Source VM
    print(f"\n--- Step 1: Stopping VM '{source_vm}' ---")
    stop_op = compute.instances().stop(project=SOURCE_PROJECT_ID, zone=source_zone, instance=source_vm).execute()
    wait_for_operation(compute, SOURCE_PROJECT_ID, stop_op)

    # Step 2: Identify Disks
    print(f"\n--- Step 2: Identifying disks for '{source_vm}' ---")
    instance_details = compute.instances().get(project=SOURCE_PROJECT_ID, zone=source_zone, instance=source_vm).execute()
    disks_to_snapshot = instance_details.get('disks', [])
    print(f"Found {len(disks_to_snapshot)} disk(s) to process.")

    images_info = []

    for disk in disks_to_snapshot:
        disk_name = os.path.basename(disk['source'])
        is_boot_disk = disk.get('boot', False)
        disk_type = "boot" if is_boot_disk else "data"
        print(f"\nProcessing {disk_type} disk: '{disk_name}'")

        # Step 3: Create Snapshot
        snapshot_name = f"{disk_name}-snapshot-{migration_id}"
        print(f"--- Step 3: Creating snapshot '{snapshot_name}' ---")
        snapshot_body = {'name': snapshot_name, 'sourceDisk': disk['source']}
        snapshot_op = compute.snapshots().insert(project=SOURCE_PROJECT_ID, body=snapshot_body).execute()
        wait_for_operation(compute, SOURCE_PROJECT_ID, snapshot_op)

        # Step 4: Create Image
        image_name = f"{disk_name}-image-{migration_id}"
        print(f"--- Step 4: Creating image '{image_name}' from snapshot ---")
        image_body = {'name': image_name, 'sourceSnapshot': f"global/snapshots/{snapshot_name}", 'storageLocations': ['us']}
        image_op = compute.images().insert(project=SOURCE_PROJECT_ID, body=image_body).execute()
        wait_for_operation(compute, SOURCE_PROJECT_ID, image_op)
        images_info.append({'name': image_name, 'type': disk_type})

        # Step 5: Share Image
        print(f"--- Step 5: Sharing image '{image_name}' ---")
        member = f"serviceAccount:service-{DESTINATION_PROJECT_NUMBER}@compute-system.iam.gserviceaccount.com"
        policy_body = {"bindings": [{"role": "roles/compute.imageUser", "members": [member]}]}
        compute.images().setIamPolicy(project=SOURCE_PROJECT_ID, resource=image_name, body=policy_body).execute()
        print(f"✅ Image '{image_name}' shared successfully.")

        print("\nWaiting for 60 seconds to avoid rate limits...")
        time.sleep(60)

    # Step 6: Create New VM
    print(f"\n--- Step 6: Creating new VM '{new_vm}' in project '{DESTINATION_PROJECT_ID}' ---")

    boot_image_info = next((img for img in images_info if img['type'] == 'boot'), None)
    data_images_info = [img for img in images_info if img['type'] == 'data']

    if not boot_image_info:
        raise Exception("❌ Boot image not found. Cannot create VM.")

    instance_body = {
        "name": new_vm,
        "machineType": f"zones/{DESTINATION_ZONE}/machineTypes/{machine_type}",
        "disks": [{"boot": True, "initializeParams": {"sourceImage": f"projects/{SOURCE_PROJECT_ID}/global/images/{boot_image_info['name']}"}, "autoDelete": True}],
        "networkInterfaces": [{"network": f"global/networks/{NETWORK_NAME}", "subnetwork": f"regions/{DESTINATION_ZONE.rsplit('-', 1)[0]}/subnetworks/{SUBNET_NAME}"}]
    }
    create_vm_op = compute.instances().insert(project=DESTINATION_PROJECT_ID, zone=DESTINATION_ZONE, body=instance_body).execute()
    wait_for_operation(compute, DESTINATION_PROJECT_ID, create_vm_op)
    print(f"✅ VM '{new_vm}' created with boot disk.")

    if data_images_info:
        print("\n--- Attaching data disks ---")
        for i, data_image in enumerate(data_images_info):
            new_disk_name = f"{new_vm}-data-disk-{i}"
            print(f"Creating data disk '{new_disk_name}'...")
            disk_body = {"name": new_disk_name, "sourceImage": f"projects/{SOURCE_PROJECT_ID}/global/images/{data_image['name']}"}
            create_disk_op = compute.disks().insert(project=DESTINATION_PROJECT_ID, zone=DESTINATION_ZONE, body=disk_body).execute()
            wait_for_operation(compute, DESTINATION_PROJECT_ID, create_disk_op)

            print(f"Attaching disk '{new_disk_name}'...")
            attach_body = {"source": f"projects/{DESTINATION_PROJECT_ID}/zones/{DESTINATION_ZONE}/disks/{new_disk_name}"}
            attach_op = compute.instances().attachDisk(project=DESTINATION_PROJECT_ID, zone=DESTINATION_ZONE, instance=new_vm, body=attach_body).execute()
            wait_for_operation(compute, DESTINATION_PROJECT_ID, attach_op)
            print(f"✅ Data disk '{new_disk_name}' attached.")

    print(f"\n🎉 Migration for VM '{source_vm}' completed successfully!")
    print("================================================================")

# --- Main Execution Logic ---

def main():
    """Finds all VMs with the specified label and migrates them."""
    compute_client = googleapiclient.discovery.build('compute', 'v1', cache_discovery=False)
    
    print(f"🔍 Searching for VMs with label '{MIGRATION_LABEL_FILTER}' in project '{SOURCE_PROJECT_ID}'...")
    
    # Use aggregatedList to find all instances across all zones that match the filter
    request = compute_client.instances().aggregatedList(project=SOURCE_PROJECT_ID, filter=MIGRATION_LABEL_FILTER)
    
    all_vms_to_migrate = []
    while request is not None:
        response = request.execute()
        for name, instances_scoped_list in response['items'].items():
            if 'instances' in instances_scoped_list:
                all_vms_to_migrate.extend(instances_scoped_list['instances'])
        request = compute_client.instances().aggregatedList_next(previous_request=request, previous_response=response)

    if not all_vms_to_migrate:
        print("No VMs found with the specified label. Exiting.")
        return

    print(f"Found {len(all_vms_to_migrate)} VM(s) to migrate. Starting process...")

    for vm in all_vms_to_migrate:
        # Construct the config for the migration function
        vm_config = {
            "source_vm_name": vm['name'],
            "source_zone": os.path.basename(vm['zone']),
            "new_vm_name": f"migrated-{vm['name']}", # Define a naming convention for new VMs
            "machine_type": os.path.basename(vm['machineType'])
        }
        
        try:
            migrate_vm(compute_client, vm_config)
        except Exception as e:
            print(f"\n❌❌ An error occurred during migration for VM '{vm_config.get('source_vm_name')}'. ❌❌")
            print(f"Error details: {e}")
            print("Moving to the next VM...")
            continue
    
    print("\nAll targeted VM migrations have been processed.")


if __name__ == '__main__':
    main()