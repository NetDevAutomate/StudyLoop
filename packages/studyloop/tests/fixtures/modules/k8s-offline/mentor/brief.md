# Mentor brief — k8s-offline

This module exists to prove the disposable-cluster path end to end. There is one drill:
confirm which cluster kubectl talks to. The point is that `KUBECONFIG` already names exactly
one context -- the cluster core created for this attempt -- so ask what the learner thinks
`KUBECONFIG` is for before explaining contexts.
