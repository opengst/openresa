# -*- coding: utf-8 -*-

##############################################################################
#
#    OpenCivil module for OpenERP, module Etat-Civil
#    Copyright (C) 200X Company (<http://website>) pyf
#
#    This file is a part of penCivil
#
#    penCivil is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    penCivil is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from osv import fields, osv
import netsvc
from datetime import datetime
#
#Wizard permettant d'emprunter des ressources à des collectivités extérieures
#

class openstc_pret_emprunt_wizard(osv.osv_memory):
    
    _name = 'openstc.pret.emprunt.wizard'
    
    _rec_name = 'date_start'
    _columns = {
                'emprunt_line':fields.one2many('openstc.pret.emprunt.line.wizard','line_id',string="Lignes d'emprunt"),
                'origin':fields.char('Document d\'origine', size=32)
                }
    
    def default_get(self, cr, uid, fields, context=None):
        ret = super(openstc_pret_emprunt_wizard, self).default_get(cr, uid, fields, context)
        #Valeurs permettant d'initialiser les lignes d'emprunts en fonction des lignes de réservation de la résa source
        print(context)
        emprunt_values = []
        if context and ('reservation_id' and 'prod_error_ids') in context:
            print(context['prod_error_ids'])
            dict_error_prods = context['prod_error_ids']
            resa = self.pool.get("hotel.reservation").browse(cr, uid, context['reservation_id'])
            ret['origin'] = resa.reservation_no
            for line in resa.reservation_line:
                #TODO: dans openstock.py (check_dispo function) mettre les clés de dict_error_prod en integer (et non str)
                if str(line.reserve_product.id) in dict_error_prods.keys():
                    #List contenant le résultat d'une requête sql calculée dans openstock.py renvoyant [qte_voulue, qte_dispo]
                    prod_error = dict_error_prods[str(line.reserve_product.id)]
                    emprunt_values.append((0,0,{'product_id':line.reserve_product.id,
                                                'qte': prod_error[0] - prod_error[1],
                                                'price_unit':line.prix_unitaire}))
            ret.update({'emprunt_line' : emprunt_values})
            print(ret)
        return ret
    
    def do_emprunt(self,cr,uid,ids,context=None):
        
        if context is None:
            context = {}
        #Dict contenant les lignes "d'achat" pour chaque fournisseur
        dict_partner = {}
        #Initialisation d'objets et de records utiles pour la création de bons de commandes
        purchase_obj = self.pool.get("purchase.order")
        #TODO: Faire une fonction globale pour récupérer l'emplacement "stock" interne (au cas où le nom changerait)
        default_location_id = self.pool.get("stock.location").search(cr, uid, [('name','=','Stock')])[0]
        origin = ""
        for emprunt in self.browse(cr, uid, ids):
            origin = emprunt.origin
            for line in emprunt.emprunt_line:
                
                if line.partner_id in dict_partner.keys():
                    dict_partner[line.partner_id.id].append((line.product_id, lien.qte))
                else:
                    dict_partner[line.partner_id.id] = [(0,0,{'product_id':line.product_id.id, 
                                                           'product_qty':line.qte, 
                                                           'date_planned':line.date_expected,
                                                           'price_unit':line.price_unit,
                                                           'name':'emprunt: ' + line.product_id.name_template,
                                                           'date_planned':line.date_expected or datetime.now()})]
        
        #Pour chaque mairie (fournisseur), on crée un bon de commande
        for (partner_id, purchase_lines) in dict_partner.items():
            #Dict qui Contient tous les éléments pour créer un nouveau bon de commande
            values = {'invoice_method':'manual',
                      'location_id':default_location_id,
                      'partner_id':partner_id,
                      'order_line':purchase_lines,
                      'origin': origin
                      }
            #On insère les modifs de l'onchange sur partner_id pour compléter les champs obligatoires
            for (key, value) in purchase_obj.onchange_partner_id(cr, uid, False, partner_id)['value'].items():
                values[key] = value
            
            print(values)      
            purchase_obj.create(cr, uid, values)
        
        return {
            'type': 'ir.actions.act_window',
            'res_model':'purchase.order',
            'view_type':'form',
            'view_mode':'tree,form',
            'domain':'[("state","=","draft")]',
            'target':'new'
        }

openstc_pret_emprunt_wizard()

class openstc_pret_emprunt_line_wizard(osv.osv_memory):
    _name="openstc.pret.emprunt.line.wizard"
    _columns={
              'line_id':fields.many2one('openstc.pret.emprunt.wizard', required=True),
              'product_id':fields.many2one('product.product', string="Ressource à Emprunter", required=True),
              'partner_id':fields.many2one('res.partner', string="Collectivité prêtant", required=True),
              'qte':fields.integer('Quantité empruntée', required=True),
              'price_unit':fields.float('Prix Unitaire', digit=(4,2)),
              'date_expected':fields.date('Date de livraison')
              }
    _order= "product_id"
    _default={
              'price_unit':0,
              'date_expected':fields.date.context_today
              }
openstc_pret_emprunt_line_wizard()

class openstc_pret_warning_no_wizard(osv.osv_memory): 
    _name = "openstc.pret.warning.dispo.wizard"
    _columns={
              }

openstc_pret_warning_no_wizard()
