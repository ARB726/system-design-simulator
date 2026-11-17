# Scoped storage checks

The adjacent four unmodified `.guard` rules are from the AWS CloudFormation Guard Rules Registry:
https://github.com/aws-cloudformation/aws-guard-rules-registry

Retrieved 17 November 2026 UTC; distributed under the registry's Apache-2.0 license (included).
They evaluate S3 public access blocks, S3 default encryption, TLS-only S3 policies, and DynamoDB encryption.
This is a targeted storage check, not a full regulatory compliance assessment or application security audit.

Run with CloudFormation Guard 3.2.2:

```powershell
./.local/cfn-guard/cfn-guard-v3-x86_64-windows-latest/cfn-guard.exe validate --rules fullstack/aws/guard --data fullstack/aws/template.json --output-format json
```
