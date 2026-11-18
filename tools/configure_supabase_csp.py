"""Allow one Supabase origin in an existing CloudFront policy; preview by default."""
import argparse
from urllib.parse import urlsplit

import boto3
from botocore.config import Config


def allow_origin(policy, origin):
    directives = [part.strip() for part in policy.split(';') if part.strip()]
    for index, directive in enumerate(directives):
        parts = directive.split()
        if parts[0] == 'connect-src':
            if origin not in parts[1:]:
                directives[index] = directive + ' ' + origin
            return '; '.join(directives)
    raise ValueError('No explicit connect-src directive; refusing to change policy.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--supabase-url', required=True)
    parser.add_argument('--distribution', default='EPSZYMYZFUTPU')
    parser.add_argument('--profile', default='system-design-simulator-free')
    parser.add_argument('--expected-project', default='675345028735')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    url = urlsplit(args.supabase_url)
    if (url.scheme != 'https' or not url.hostname or not url.hostname.endswith('.supabase.co')
            or url.username or url.password or url.port or url.path not in ('', '/')
            or url.query or url.fragment):
        parser.error('Use the HTTPS root URL of the intended Supabase project.')
    origin = 'https://' + url.hostname
    session = boto3.Session(profile_name=args.profile, region_name='us-east-2')
    config = Config(connect_timeout=10, read_timeout=40,
                    retries={'mode': 'standard', 'max_attempts': 3})
    if session.client('sts', config=config).get_caller_identity()['Account'] != args.expected_project:
        raise RuntimeError('Wrong AWS project; no changes made.')
    print('AWS plan:', session.client('freetier', config=config).get_account_plan_state()['accountPlanType'], flush=True)
    cf = session.client('cloudfront', region_name='us-east-1', config=config)
    distribution = cf.get_distribution_config(Id=args.distribution)['DistributionConfig']
    policy_id = distribution['DefaultCacheBehavior']['ResponseHeadersPolicyId']
    response = cf.get_response_headers_policy(Id=policy_id)
    policy = response['ResponseHeadersPolicy']['ResponseHeadersPolicyConfig']
    csp = policy['SecurityHeadersConfig']['ContentSecurityPolicy']
    original = csp['ContentSecurityPolicy']
    updated = allow_origin(original, origin)
    print('Allow browser connections to:', origin, flush=True)
    if original == updated:
        print('Origin is already allowed; no changes needed.')
    elif args.apply:
        csp['ContentSecurityPolicy'] = updated
        # CloudFront GET can return empty optional blocks that UPDATE rejects.
        security = policy['SecurityHeadersConfig']
        for name in list(security):
            if security[name] == {}:
                del security[name]
        cf.update_response_headers_policy(Id=policy_id, IfMatch=response['ETag'],
                                          ResponseHeadersPolicyConfig=policy)
        print('Updated existing CloudFront policy; other directives preserved.', flush=True)
    else:
        print('Preview only. Add --apply to update the existing policy.')


if __name__ == '__main__':
    main()
