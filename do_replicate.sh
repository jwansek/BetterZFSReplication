#!/bin/sh

# Assumes we already have an initial backup (with just -R)
# Ignores sub-datasets that don't have a snapshot (make sure
# this is what you want)

DEST_URL=$1
SRC_POOL=$2
DEST_POOL=$3

OLD_SNAP=$(ssh root@$DEST_URL "zfs list -t snapshot -o name $DEST_POOL | tail -n1" | cut -d "@" -f2)
NEW_SNAP=$(zfs list -t snapshot -o name $SRC_POOL | tail -n1 | cut -d "@" -f2)

echo "Old snapshot: '$OLD_SNAP'"
echo "New snapshot: '$NEW_SNAP'"

if [ "$OLD_SNAP" = "$NEW_SNAP" ]; then
    echo "Up to date, nothing to do..."
else
    zfs send -Rw -I "$SRC_POOL"@"$OLD_SNAP" "$SRC_POOL"@"$NEW_SNAP" -s | pv | ssh root@$DEST_URL "zfs recv -Fvdu $DEST_POOL"
    echo "Finished backing up: '$OLD_SNAP' to '$NEW_SNAP'"
fi
