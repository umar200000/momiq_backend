"""Validate the tested admin pin and fail closed on incompatible deployed assets."""
import argparse
import json
from pathlib import Path
import re

ASSETS=('index.html','app.js','style.css','wallet.js','chat.js','reviews.js','support.js',
        'disputes.js','bookings.js','metrics.js','work_queue.js')


def document(path):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate release manifest key')
            result[key]=value
        return result
    if path.stat().st_size>4096:raise ValueError('Release manifest is too large')
    result=json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=pairs)
    if not isinstance(result,dict):raise ValueError('Release manifest must be an object')
    return result


def admin_pin(backend):
    pin=document(Path(backend)/'admin-release.json')
    if (set(pin)!={'repository','revision','contractVersion'} or pin['repository']!='umar200000/momiq_admin'
            or not isinstance(pin['revision'],str) or not re.fullmatch(r'[a-f0-9]{40}',pin['revision'])
            or type(pin['contractVersion']) is not int or pin['contractVersion']!=1):
        raise ValueError('Invalid or unsupported tested admin release pin')
    return pin


def validate(backend,admin,actual_revision=None):
    pin=admin_pin(backend);root=Path(admin).resolve()
    manifest=root/'release-contract.json'
    if not manifest.resolve().is_relative_to(root):raise ValueError('Admin manifest escapes its release directory')
    contract=document(manifest)
    if (set(contract)!={'backendContractVersion'} or type(contract['backendContractVersion']) is not int
            or contract['backendContractVersion']!=pin['contractVersion']):
        raise ValueError('Backend/admin contract mismatch; stage a compatible pair before switching traffic')
    for name in ASSETS:
        asset=root/name
        if not asset.resolve().is_relative_to(root) or not asset.is_file() or asset.stat().st_size==0:
            raise ValueError('Missing, empty or escaped admin asset: '+name)
    if actual_revision is not None and actual_revision!=pin['revision']:
        raise ValueError('Admin checkout does not match the exact revision tested by this backend')
    return pin


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',type=Path,required=True)
    parser.add_argument('--admin',type=Path)
    parser.add_argument('--actual-admin-revision')
    parser.add_argument('--print-revision',action='store_true')
    args=parser.parse_args()
    try:
        if args.print_revision:
            if args.admin is not None or args.actual_admin_revision is not None:parser.error('Choose pin output or pair validation')
            print(admin_pin(args.backend)['revision'])
        else:
            if args.admin is None:parser.error('--admin is required for pair validation')
            result=validate(args.backend,args.admin,args.actual_admin_revision)
            print('Backend/admin contract verified:',result['contractVersion'])
    except (OSError,ValueError) as error:parser.exit(1,'Release pair check failed: '+str(error)+'\n')


if __name__=='__main__':main()
