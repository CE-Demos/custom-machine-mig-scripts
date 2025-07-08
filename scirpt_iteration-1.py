import googleapiclient.discovery
import time
from datetime import datetime
import os 

# --- Configuration ---
SOURCE_PROJECT_ID = "ce-ai-chatbot"
SOURCE_ZONE = "us-central1-c"  # e.g., "us-central1-a"
SOURCE_VM_NAME = "my-base-vm"
IMAGE_NAME = "boot-image"  # e.g., "my-custom-image"
DESTINATION_PROJECT_ID = "ce-testing-465204"
DESTINATION_PROJECT_NUMBER="526827734705"
NEW_VM_NAME = "migrated-vm"
MACHINE_TYPE = "e2-medium"
NETWORK_NAME = "new-base-network"
SUBNET_NAME = "new-first-subnet"
DESTINATION_ZONE = "us-central1-a"

SERVICE_ACCOUNT_FILE = "/path/to/your/service-account-key.json" # Path to the downloaded JSON key

MIGRATION_ID = datetime.now().strftime("%Y%m%d-%H%M%S")

# --- Helper Functions ---

def wait_for_operation(compute, project, operation):
    """
    Waits for a GCP Compute Engine operation to complete.
    Handles both global and zonal operations automatically.
    """
    print(f"⏳ Waiting for operation '{operation['name']}'...")

    while True:
        # Check if the operation is zonal or global
        if 'zone' in operation:
            result = compute.zoneOperations().get(
                project=project,
                zone=os.path.basename(operation['zone']), # Extracts zone from URL
                operation=operation['name']
            ).execute()
        else:
            result = compute.globalOperations().get(
                project=project,
                operation=operation['name']
            ).execute()

        # If the operation is 'DONE', exit the loop
        if result['status'] == 'DONE':
            print("✅ Operation finished.")
            if 'error' in result:
                print("❌ Operation failed!")
                raise Exception(result['error'])
            return result
        
        time.sleep(3)

# --- Main Script Logic ---

def main():
    """Main function to orchestrate the VM migration."""
    compute = googleapiclient.discovery.build('compute', 'v1', cache_discovery=False)
    print(f"🚀 Starting migration for VM '{SOURCE_VM_NAME}' with Migration ID: {MIGRATION_ID}")

    # Step 1: Stop the Source VM
    print(f"\n--- Step 1: Stopping VM '{SOURCE_VM_NAME}' ---")
    stop_op = compute.instances().stop(project=SOURCE_PROJECT_ID, zone=SOURCE_ZONE, instance=SOURCE_VM_NAME).execute()
    wait_for_operation(compute, SOURCE_PROJECT_ID, stop_op)

    # Step 2: Identify Disks
    print(f"\n--- Step 2: Identifying disks for '{SOURCE_VM_NAME}' ---")
    instance_details = compute.instances().get(project=SOURCE_PROJECT_ID, zone=SOURCE_ZONE, instance=SOURCE_VM_NAME).execute()
    disks_to_snapshot = instance_details.get('disks', [])
    print(f"Found {len(disks_to_snapshot)} disk(s) to process.")

    images_info = []

    for disk in disks_to_snapshot:
        disk_name = os.path.basename(disk['source'])
        is_boot_disk = disk.get('boot', False)
        disk_type = "boot" if is_boot_disk else "data"
        print(f"\nProcessing {disk_type} disk: '{disk_name}'")

        # Step 3: Create Snapshot of the Disk
        snapshot_name = f"{disk_name}-snapshot-{MIGRATION_ID}"
        print(f"--- Step 3: Creating snapshot '{snapshot_name}' ---")
        snapshot_body = {'name': snapshot_name, 'sourceDisk': disk['source']}
        snapshot_op = compute.snapshots().insert(project=SOURCE_PROJECT_ID, body=snapshot_body).execute()
        wait_for_operation(compute, SOURCE_PROJECT_ID, snapshot_op)

        # Step 4: Create Custom Image from Snapshot
        image_name = f"{disk_name}-image-{MIGRATION_ID}"
        print(f"--- Step 4: Creating image '{image_name}' from snapshot ---")
        image_body = {'name': image_name, 'sourceSnapshot': f"global/snapshots/{snapshot_name}", 'storageLocations': ['us']}
        image_op = compute.images().insert(project=SOURCE_PROJECT_ID, body=image_body).execute()
        wait_for_operation(compute, SOURCE_PROJECT_ID, image_op)
        images_info.append({'name': image_name, 'type': disk_type})

        # Step 5: Share the Custom Image with the Destination Project
        print(f"--- Step 5: Sharing image '{image_name}' with project '{DESTINATION_PROJECT_ID}' ---")
        member = f"serviceAccount:service-{DESTINATION_PROJECT_NUMBER}@compute-system.iam.gserviceaccount.com"
        policy_body = {"bindings": [{"role": "roles/compute.imageUser", "members": [member]}]}
        compute.images().setIamPolicy(project=SOURCE_PROJECT_ID, resource=image_name, body=policy_body).execute()
        print(f"✅ Image '{image_name}' shared successfully.")

        # Add delay to avoid rate-limiting errors
        print("\nWaiting for 60 seconds to avoid rate limits...")
        time.sleep(60)

    # Step 6: Create the New VM in the Destination Project
    print(f"\n--- Step 6: Creating new VM '{NEW_VM_NAME}' in project '{DESTINATION_PROJECT_ID}' ---")

    boot_image_info = next((img for img in images_info if img['type'] == 'boot'), None)
    data_images_info = [img for img in images_info if img['type'] == 'data']

    if not boot_image_info:
        raise Exception("❌ Boot image not found. Cannot create VM.")

    instance_body = {
        "name": NEW_VM_NAME,
        "machineType": f"zones/{DESTINATION_ZONE}/machineTypes/{MACHINE_TYPE}",
        "disks": [{
            "boot": True,
            "initializeParams": {"sourceImage": f"projects/{SOURCE_PROJECT_ID}/global/images/{boot_image_info['name']}"},
            "autoDelete": True
        }],
        "networkInterfaces": [{
            "network": f"global/networks/{NETWORK_NAME}",
            "subnetwork": f"regions/{DESTINATION_ZONE.rsplit('-', 1)[0]}/subnetworks/{SUBNET_NAME}"
        }]
    }

    create_vm_op = compute.instances().insert(project=DESTINATION_PROJECT_ID, zone=DESTINATION_ZONE, body=instance_body).execute()
    wait_for_operation(compute, DESTINATION_PROJECT_ID, create_vm_op)
    print(f"✅ VM '{NEW_VM_NAME}' created with boot disk.")

    if data_images_info:
        print("\n--- Attaching data disks ---")
        for i, data_image in enumerate(data_images_info):
            new_disk_name = f"{NEW_VM_NAME}-data-disk-{i}"
            print(f"Creating data disk '{new_disk_name}' from image '{data_image['name']}'...")

            disk_body = {"name": new_disk_name, "sourceImage": f"projects/{SOURCE_PROJECT_ID}/global/images/{data_image['name']}"}
            create_disk_op = compute.disks().insert(project=DESTINATION_PROJECT_ID, zone=DESTINATION_ZONE, body=disk_body).execute()
            wait_for_operation(compute, DESTINATION_PROJECT_ID, create_disk_op)

            print(f"Attaching disk '{new_disk_name}' to VM '{NEW_VM_NAME}'...")
            attach_body = {"source": f"projects/{DESTINATION_PROJECT_ID}/zones/{DESTINATION_ZONE}/disks/{new_disk_name}"}
            attach_op = compute.instances().attachDisk(project=DESTINATION_PROJECT_ID, zone=DESTINATION_ZONE, instance=NEW_VM_NAME, body=attach_body).execute()
            wait_for_operation(compute, DESTINATION_PROJECT_ID, attach_op)
            print(f"✅ Data disk '{new_disk_name}' attached.")
    
    print("\n🎉 Migration script completed successfully!")

if __name__ == '__main__':
    main()