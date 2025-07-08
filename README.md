# Steps Performed by the script

Steps:

## 1. Stop the Source VM (Optional but Recommended):

```
gcloud compute instances stop SOURCE_VM_NAME --zone=SOURCE_ZONE --project=SOURCE_PROJECT_ID
Replace SOURCE_VM_NAME, SOURCE_ZONE, and SOURCE_PROJECT_ID with your VM's details.
```

## 2. Identify Disks: Determine all persistent disks attached to your source VM, especially the boot disk and any additional data disks.

```
gcloud compute instances describe SOURCE_VM_NAME --zone=SOURCE_ZONE --project=SOURCE_PROJECT_ID --format="list(name,disks)"
```

## 3. Create Snapshots of All Disks: Create a snapshot for each disk associated with your VM. Snapshots are global resources, so they can be accessed from any project, provided the correct permissions are set.

### For the boot disk

``` 
gcloud compute snapshots create BOOT_DISK_SNAPSHOT_NAME \
    --source-disk=BOOT_DISK_NAME \
    --source-disk-zone=SOURCE_ZONE \
    --project=SOURCE_PROJECT_ID
```

### For any data disks (repeat for each data disk)

```
gcloud compute snapshots create DATA_DISK_SNAPSHOT_NAME \
    --source-disk=DATA_DISK_NAME \
    --source-disk-zone=SOURCE_ZONE \
    --project=SOURCE_PROJECT_ID
Choose meaningful SNAPSHOT_NAMEs.
```

## 4. Create Custom Images from Snapshots (Optional but Recommended for Reusability): Creating a custom image from the snapshot makes it easier to create multiple VMs later or to manage the "golden image." Images are also global resources.

### For the boot disk

```
gcloud compute images create BOOT_IMAGE_NAME \
    --source-snapshot=BOOT_DISK_SNAPSHOT_NAME \
    --project=SOURCE_PROJECT_ID \
    --storage-location=GLOBAL_LOCATION_OR_MULTI_REGION # e.g., us, asia, eu, or us-central1 etc.
```

### For any data disks (repeat for each data disk)

```
gcloud compute images create DATA_IMAGE_NAME \
    --source-snapshot=DATA_DISK_SNAPSHOT_NAME \
    --project=SOURCE_PROJECT_ID \
    --storage-location=GLOBAL_LOCATION_OR_MULTI_REGION
Using a multi-region like us for storage-location makes it globally accessible.
```

## 5. Share the Custom Image(s) with the Destination Project: This is a crucial step. Grant the Compute Image User role to the service account of your destination project (or a specific user creating the VM) on the source project or on the specific image.

Grant permission on the source project before running the script (easier for multiple images/VMs):

```
gcloud projects add-iam-policy-binding SOURCE_PROJECT_ID \
    --member='serviceAccount:service-DESTINATION_PROJECT_NUMBER@compute-system.iam.gserviceaccount.com' \
    --role='roles/compute.imageUser'
```

Find your DESTINATION_PROJECT_NUMBER in the GCP Console (Project Info Dashboard) or via gcloud projects describe DESTINATION_PROJECT_ID --format="value(projectNumber)".


## 6. Create the New VM in the Destination Project: Now, in your destination project, create a new VM instance using the custom image(s) from the source project.

```
gcloud compute instances create NEW_VM_NAME \
    --project=DESTINATION_PROJECT_ID \
    --zone=DESTINATION_ZONE \
    --machine-type=MACHINE_TYPE \
    --image=BOOT_IMAGE_NAME \
    --image-project=SOURCE_PROJECT_ID \
    --network=NETWORK_NAME \
    --subnet=SUBNET_NAME \
    # Add any other required flags: --metadata, --tags, --service-account, --scopes, etc.
```

If you have data disks:

```
gcloud compute disks create NEW_DATA_DISK_NAME \
    --image=DATA_IMAGE_NAME \
    --image-project=SOURCE_PROJECT_ID \
    --zone=DESTINATION_ZONE \
    --project=DESTINATION_PROJECT_ID
```

```
gcloud compute instances attach-disk NEW_VM_NAME \
    --disk=NEW_DATA_DISK_NAME \
    --zone=DESTINATION_ZONE \
    --project=DESTINATION_PROJECT_ID
```


# Note

Do change the values of the configuration variables to align with your project and instance details before running the script.



