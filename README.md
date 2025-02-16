# BetterZFSReplication
Do ZFS replication in a better way than the TrueNAS UI

Because the UI abstracts away the raw CLI options and I don't know what it's really doing

![image](https://i.imgur.com/1dFxotg.png)

# autoBackup
[`autoBackup`](/autoBackup/) is a nice script that boots another TrueNAS machine, runs some ZFS replication tasks,
and then turns itself off again.

The script consists of a `master` TrueNAS and a `slave` TrueNAS. It is assumed that the `master` TrueNAS is already
on when this script is executed. The `slave` TrueNAS is switched on with the use of a Tasmota-flashed power plug, like [this](https://www.aliexpress.com/item/1005008170716102.html?spm=a2g0o.productlist.main.3.aa15JW8VJW8Vv1&algo_pvid=a947a69a-023e-42be-85fc-8c6e3000e4e1&algo_exp_id=a947a69a-023e-42be-85fc-8c6e3000e4e1-1&pdp_ext_f=%7B%22order%22%3A%2232%22%2C%22eval%22%3A%221%22%7D&pdp_npi=4%40dis%21GBP%2116.42%217.00%21%21%21145.82%2162.16%21%402103846917397249539965105e8199%2112000044086004119%21sea%21UK%210%21ABX&curPageLogUid=eQIYf54PMGje&utparam-url=scene%3Asearch%7Cquery_from%3A), using MQTT.

The script waits until the slave TrueNAS can recieve API requests, then runs a number of named ZFS replication tasks, as configured in the UI.
Therefore these tasks should not be set to run automatically in the TrueNAS UI. The tasks can be both on the `master` TrueNAS (push tasks),
and on the `slave` TrueNAS (pull tasks). Once all the replication tasks are completed, if the `slave` TrueNAS was switched on by this script,
it is shut down, and once the plug is pulling 0w, which implies the TrueNAS has fully shut down, the Tasmota plug is switched off.

If the Tasmota MQTT plug was already on when the script starts, it implies that the `slave` TrueNAS was started manually, so it won't automatically
be switched off.

It is recommended to run ZFS scrub tasks manually occasionally, otherwise they probably won't be run by TrueNAS.

A Dockerfile is provided so you can automatically run this script as a cronjob.

The MQTT Tamsmota stuff is pretty specific to my setup so might not be too useful to others; but the TrueNAS API stuff might be useful to other people. It probably wouldn't be too hard to make this work with wake-on-lan instead. We are using the HTTP API instead of the sockets API, since the sockets API seems to change quite a lot. We use standard TrueNAS API keys.

